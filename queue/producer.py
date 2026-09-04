import json
import time
import logging
from typing import Optional
import redis.asyncio as aioredis
from ingestion.normalizer import DealPayload
from queue.redis_client import RedisConnectionManager

logger = logging.getLogger("DealProducer")

class DealProducer:
    """
    Enqueues incoming raw or normalized deal payloads into Redis.
    """
    INCOMING_QUEUE = "deals:incoming"

    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self._redis = redis_client

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = RedisConnectionManager.get_client()
        return self._redis

    async def enqueue_deal(self, deal: DealPayload) -> bool:
        try:
            if not deal.timestamp:
                deal.timestamp = time.time()

            payload_json = deal.model_dump_json()
            await self.redis.rpush(self.INCOMING_QUEUE, payload_json)
            logger.info(f"Successfully enqueued deal: {deal.title} (Source: {deal.source})")
            return True
        except Exception as e:
            logger.error(f"Failed to enqueue deal: {e}", exc_info=True)
            return False
