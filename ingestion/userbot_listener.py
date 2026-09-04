import os
import sys
import asyncio
import logging
from typing import List, Optional
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from telethon.errors import FloodWaitError

from config import settings
from ingestion.normalizer import DealNormalizer, DealPayload
from queue.producer import DealProducer

logger = logging.getLogger("UserbotListener")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

class UserbotListener:
    """
    Telethon MTProto listener that intercepts posts from deal channels,
    extracts text, media, buttons, and hyperlinks, and enqueues to Redis.
    """
    def __init__(self, session_name: str = None, api_id: int = None, api_hash: str = None):
        self.session_name = session_name or settings.TELEGRAM_SESSION_NAME
        self.api_id = api_id or settings.TELEGRAM_API_ID
        self.api_hash = api_hash or settings.TELEGRAM_API_HASH
        self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
        self.producer = DealProducer()
        self.target_channels = settings.source_channels

    async def start(self):
        logger.info("Initializing Telethon Userbot Listener...")
        if not self.api_id or not self.api_hash:
            logger.error("TELEGRAM_API_ID and TELEGRAM_API_HASH must be provided in .env!")
            raise ValueError("Missing Telegram API credentials.")

        await self.client.start()
        me = await self.client.get_me()
        logger.info(f"Userbot authenticated as: {me.first_name} (@{me.username or 'NoUsername'})")
        logger.info(f"Monitoring channels: {self.target_channels}")

        # Resolve channel entities
        resolved_entities = []
        for ch in self.target_channels:
            try:
                entity = await self.client.get_entity(ch)
                resolved_entities.append(entity)
                logger.info(f"Successfully subscribed to channel: {ch} (ID: {entity.id})")
            except Exception as e:
                logger.warning(f"Could not resolve channel {ch}: {e}")

        if not resolved_entities:
            logger.warning("No valid channels resolved. Listening to all incoming channel posts as fallback...")
            entities_to_watch = None
        else:
            entities_to_watch = resolved_entities

        @self.client.on(events.NewMessage(chats=entities_to_watch))
        async def handle_new_message(event):
            try:
                msg = event.message
                raw_text = msg.message or ""
                
                # Extract button URLs if message has inline buttons
                button_urls = []
                if msg.buttons:
                    for row in msg.buttons:
                        for btn in row:
                            if hasattr(btn, 'url') and btn.url:
                                button_urls.append(btn.url)

                # Combine text and button links
                if button_urls:
                    raw_text += "\n" + "\n".join(button_urls)

                if not raw_text.strip():
                    return

                sender_name = "unknown_channel"
                try:
                    chat = await event.get_chat()
                    sender_name = getattr(chat, 'username', None) or getattr(chat, 'title', str(event.chat_id))
                except Exception:
                    pass

                # Check if there is media to download
                media_path = None
                if msg.media and isinstance(msg.media, (MessageMediaPhoto, MessageMediaDocument)):
                    os.makedirs("/tmp/sasta_maal_media", exist_ok=True)
                    try:
                        media_path = await self.client.download_media(
                            msg.media, 
                            file=f"/tmp/sasta_maal_media/{msg.id}_{event.chat_id}"
                        )
                        logger.info(f"Downloaded deal media: {media_path}")
                    except Exception as me_err:
                        logger.warning(f"Failed to download media: {me_err}")

                normalized_deal = DealNormalizer.normalize(
                    raw_text=raw_text,
                    source=f"telethon:{sender_name}",
                    image_path=media_path
                )

                # Skip if no links detected in post
                if not normalized_deal.extracted_urls:
                    logger.debug(f"Skipping post from {sender_name}: No URLs found.")
                    return

                logger.info(f"Intercepted deal from [{sender_name}]: {normalized_deal.title} | URLs: {len(normalized_deal.extracted_urls)}")
                
                # Push to Redis stream/queue
                await self.producer.enqueue_deal(normalized_deal)

            except FloodWaitError as fwe:
                logger.error(f"Telegram FloodWait triggered: Sleeping for {fwe.seconds}s")
                await asyncio.sleep(fwe.seconds)
            except Exception as e:
                logger.error(f"Error handling channel message: {e}", exc_info=True)

        logger.info("Userbot listener is actively running. Awaiting deals...")
        await self.client.run_until_disconnected()

if __name__ == "__main__":
    listener = UserbotListener()
    try:
        asyncio.run(listener.start())
    except KeyboardInterrupt:
        logger.info("Userbot listener stopped by user.")
