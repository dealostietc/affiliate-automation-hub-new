import os
import json
import asyncio
import logging
from typing import Optional
import httpx

from config import settings
from ingestion.normalizer import DealPayload
from transformer.affiliate_engine import AffiliateEngine
from transformer.deduplicator import DeduplicationEngine
from transformer.formatter import DealFormatter
from broadcaster.telegram_broadcaster import TelegramBroadcaster
from broadcaster.whatsapp_cloud import WhatsAppCloudBroadcaster
from queue.redis_client import RedisConnectionManager

logger = logging.getLogger("PipelineWorker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

class DealPipelineWorker:
    """
    Core distributed consumer worker that processes queued raw deals:
    1. Unshortens and monetizes links.
    2. Deduplicates against Redis sliding window and historical lows.
    3. Formats conversion-optimized messages.
    4. Dispatches to Telegram and WhatsApp.
    """
    INCOMING_QUEUE = "deals:incoming"
    DEAD_LETTER_QUEUE = "deals:dead_letter"

    def __init__(self):
        self.redis = RedisConnectionManager.get_client()
        self.affiliate_engine = AffiliateEngine()
        self.deduplicator = DeduplicationEngine(self.redis)
        self.telegram_broadcaster = TelegramBroadcaster()
        self.whatsapp_cloud = WhatsAppCloudBroadcaster()
        self.whatsapp_baileys_url = settings.WHATSAPP_BAILEYS_ENDPOINT
        self.is_running = True

    async def dispatch_whatsapp_baileys(self, formatted_data: dict) -> bool:
        """Sends deal to the local Node.js Baileys microservice."""
        if not self.whatsapp_baileys_url:
            return False

        payload = {
            "deal": formatted_data,
            "targetGroups": settings.whatsapp_group_jids
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.whatsapp_baileys_url, json=payload)
                if resp.status_code in [200, 202]:
                    logger.info("Successfully queued deal with WhatsApp Baileys microservice.")
                    return True
                else:
                    logger.warning(f"Baileys microservice responded with status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Failed to communicate with WhatsApp Baileys service at {self.whatsapp_baileys_url}: {e}")
        return False

    async def process_single_deal(self, raw_payload_json: str):
        try:
            data = json.loads(raw_payload_json)
            deal = DealPayload(**data)
            logger.info(f"Processing deal: {deal.title} (Source: {deal.source})")

            # 1. Affiliate Link Transformation
            primary_url = deal.extracted_urls[0] if deal.extracted_urls else None
            if primary_url:
                result = await self.affiliate_engine.process_url(primary_url)
                deal.monetized_url = result["monetized_url"]
                deal.platform = result["platform"]
                canonical_id = result["canonical_id"]
            else:
                canonical_id = deal.title or "unknown_product"

            # 2. Deduplication & Historical Price Check
            deal.product_hash = DeduplicationEngine.generate_product_hash(canonical_id)
            should_broadcast, reason, history = await self.deduplicator.evaluate_deal(
                deal.product_hash, deal.current_price
            )

            if not should_broadcast:
                logger.info(f"Deal suppressed by deduplicator. Reason: {reason} | Hash: {deal.product_hash}")
                return

            logger.info(f"Deal passed deduplication! Reason: {reason} | Hash: {deal.product_hash}")

            # 3. Message Formatting
            tg_data = DealFormatter.format_telegram(deal, drop_reason=reason)
            wa_data = DealFormatter.format_whatsapp(deal, drop_reason=reason)

            # 4. Multi-Channel Dispatch
            # A. Telegram
            tg_success = await self.telegram_broadcaster.broadcast_deal(tg_data)
            logger.info(f"Telegram broadcast result: {tg_success}")

            # B. WhatsApp
            if settings.WHATSAPP_MODE == "baileys":
                wa_success = await self.dispatch_whatsapp_baileys(wa_data)
                logger.info(f"WhatsApp Baileys dispatch result: {wa_success}")
            elif settings.WHATSAPP_MODE == "cloud_api":
                wa_success = await self.whatsapp_cloud.broadcast_deal(wa_data)
                logger.info(f"WhatsApp Cloud API dispatch result: {wa_success}")

        except Exception as e:
            logger.error(f"Error processing deal payload: {e}", exc_info=True)
            # Push to Dead Letter Queue for inspection
            try:
                await self.redis.rpush(self.DEAD_LETTER_QUEUE, raw_payload_json)
            except Exception as dlq_err:
                logger.critical(f"Failed pushing to dead-letter queue: {dlq_err}")

    async def start(self):
        logger.info(f"Starting Deal Pipeline Worker. Listening on queue '{self.INCOMING_QUEUE}'...")
        while self.is_running:
            try:
                # Blocking pop with 2s timeout
                result = await self.redis.blpop(self.INCOMING_QUEUE, timeout=2)
                if result:
                    _, raw_payload = result
                    await self.process_single_deal(raw_payload)
            except asyncio.CancelledError:
                logger.info("Pipeline worker cancellation received.")
                break
            except Exception as e:
                logger.error(f"Worker queue polling error: {e}")
                await asyncio.sleep(2.0)

    def stop(self):
        self.is_running = False

if __name__ == "__main__":
    worker = DealPipelineWorker()
    try:
        asyncio.run(worker.start())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")
