import express from 'express';
import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  delay
} from '@whiskeysockets/baileys';
import pino from 'pino';
import qrcode from 'qrcode-terminal';
import fs from 'fs';
import path from 'path';
import dotenv from 'dotenv';

dotenv.config({ path: '../../.env' });

const PORT = process.env.WHATSAPP_SERVICE_PORT || 3001;
const SESSION_DIR = path.resolve('./session');

// Ensure session directory exists
if (!fs.existsSync(SESSION_DIR)) {
  fs.mkdirSync(SESSION_DIR, { recursive: true });
}

const logger = pino({ level: 'info' });
const app = express();
app.use(express.json());

let sock = null;
let isConnected = false;

// Anti-ban Dispatch Queue
const dispatchQueue = [];
let isProcessingQueue = false;

/**
 * Generates randomized jitter delay between min and max seconds
 */
const getRandomJitterMs = (minSec = 8, maxSec = 25) => {
  const ms = Math.floor(Math.random() * (maxSec - minSec + 1) + minSec) * 1000;
  return ms;
};

/**
 * Simulates human presence (typing...) before dispatching to group
 */
async function simulateHumanPresence(jid) {
  try {
    if (!sock) return;
    await sock.sendPresenceUpdate('composing', jid);
    // Simulate typing for 2.5 to 5.0 seconds
    const typingDuration = Math.floor(Math.random() * 2500) + 2500;
    await delay(typingDuration);
    await sock.sendPresenceUpdate('paused', jid);
  } catch (err) {
    logger.warn(`Could not simulate presence for ${jid}: ${err.message}`);
  }
}

/**
 * Initializes Baileys WhatsApp Socket
 */
async function connectToWhatsApp() {
  const { state, saveCreds } = await useMultiFileAuthState(SESSION_DIR);
  const { version, isLatest } = await fetchLatestBaileysVersion();
  logger.info(`Starting Baileys v${version.join('.')} (isLatest: ${isLatest})`);

  sock = makeWASocket({
    version,
    logger: pino({ level: 'silent' }),
    printQRInTerminal: false,
    auth: state,
    browser: ['Ubuntu', 'Chrome', '122.0.6261.94'],
    generateHighQualityLinkPreview: true,
    syncFullHistory: false
  });

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log('\n================== SCAN WHATSAPP QR CODE ==================');
      qrcode.generate(qr, { small: true });
      console.log('Scan the QR code above with your WhatsApp device to link.');
      console.log('===========================================================\n');
    }

    if (connection === 'close') {
      isConnected = false;
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      logger.warn(`Connection closed due to ${lastDisconnect?.error}, reconnecting: ${shouldReconnect}`);

      if (shouldReconnect) {
        // Backoff before reconnecting
        await delay(5000);
        connectToWhatsApp();
      } else {
        logger.error('WhatsApp session logged out. Clear session/ and restart to re-authenticate.');
      }
    } else if (connection === 'open') {
      isConnected = true;
      logger.info('WhatsApp Baileys socket successfully connected and authenticated!');
    }
  });

  sock.ev.on('creds.update', saveCreds);
}

/**
 * Queue Consumer processing deal broadcasts with anti-ban delays
 */
async function processDispatchQueue() {
  if (isProcessingQueue) return;
  isProcessingQueue = true;

  logger.info('WhatsApp dispatch queue processor started.');

  while (dispatchQueue.length > 0) {
    const task = dispatchQueue.shift();
    const { deal, groupJids } = task;

    if (!isConnected || !sock) {
      logger.warn('WhatsApp not connected. Re-queuing job at end of queue.');
      dispatchQueue.push(task);
      await delay(10000);
      continue;
    }

    let groupsProcessed = 0;

    for (const jid of groupJids) {
      try {
        logger.info(`Preparing broadcast to WhatsApp group: ${jid}`);
        
        // 1. Simulate human presence
        await simulateHumanPresence(jid);

        // 2. Prepare message content
        const messageText = deal.text;
        const imagePath = deal.image_path;
        const imageUrl = deal.image_url;

        if (imagePath && fs.existsSync(imagePath)) {
          await sock.sendMessage(jid, {
            image: fs.readFileSync(imagePath),
            caption: messageText
          });
        } else if (imageUrl && imageUrl.startsWith('http')) {
          await sock.sendMessage(jid, {
            image: { url: imageUrl },
            caption: messageText
          });
        } else {
          await sock.sendMessage(jid, { text: messageText });
        }

        logger.info(`Dispatched deal to group ${jid}`);
        groupsProcessed++;

        // Anti-ban Batch Cooldown: If 5 groups processed in a row, take a long break
        if (groupsProcessed % 5 === 0 && groupsProcessed < groupJids.length) {
          const batchCooldown = Math.floor(Math.random() * 45000) + 45000;
          logger.info(`Anti-ban batch limit reached. Cooling down for ${batchCooldown / 1000}s...`);
          await delay(batchCooldown);
        } else {
          // Anti-ban Jitter: 8 to 25 seconds delay between consecutive group posts
          const jitterDelay = getRandomJitterMs(8, 25);
          logger.info(`Anti-ban jitter delay: Sleeping ${jitterDelay / 1000}s before next group...`);
          await delay(jitterDelay);
        }

      } catch (err) {
        logger.error(`Failed to dispatch deal to ${jid}: ${err.message}`);
      }
    }
  }

  isProcessingQueue = false;
  logger.info('WhatsApp dispatch queue is now empty.');
}

// ---------------- Express Endpoints ----------------

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    whatsappConnected: isConnected,
    queueLength: dispatchQueue.length,
    isProcessingQueue
  });
});

// Endpoint called by Python deal aggregator worker
app.post('/send-deal', (req, res) => {
  const { deal, targetGroups } = req.body;

  if (!deal || !deal.text) {
    return res.status(400).json({ error: 'deal payload with text is required' });
  }

  // Use configured group JIDs if none specified in payload
  const envGroups = process.env.WHATSAPP_GROUP_JIDS
    ? process.env.WHATSAPP_GROUP_JIDS.split(',').map(s => s.trim()).filter(Boolean)
    : [];
  
  const groups = (targetGroups && targetGroups.length > 0) ? targetGroups : envGroups;

  if (groups.length === 0) {
    logger.warn('No WhatsApp target groups configured.');
    return res.status(400).json({ error: 'No recipient groups specified or found in environment.' });
  }

  dispatchQueue.push({ deal, groupJids: groups });
  logger.info(`Enqueued deal for ${groups.length} groups. Queue depth: ${dispatchQueue.length}`);

  // Trigger processor
  processDispatchQueue();

  res.status(202).json({
    status: 'queued',
    queuePosition: dispatchQueue.length,
    targetGroupsCount: groups.length
  });
});

// Start Express and WhatsApp connection
app.listen(PORT, () => {
  logger.info(`WhatsApp Baileys microservice listening on HTTP port ${PORT}`);
  connectToWhatsApp().catch((err) => logger.error('Error starting Baileys:', err));
});
