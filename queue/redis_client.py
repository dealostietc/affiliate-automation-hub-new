import logging
from typing import Optional
import redis.asyncio as aioredis
from config import settings

logger = logging.getLogger("RedisClient")

class RedisConnectionManager:
    _pool: Optional[aioredis.ConnectionPool] = None

    @classmethod
    def get_pool(cls) -> aioredis.ConnectionPool:
        if cls._pool is None:
            logger.info(f"Connecting to Redis at {settings.REDIS_URL}")
            cls._pool = aioredis.ConnectionPool.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                max_connections=50
            )
        return cls._pool

    @classmethod
    def get_client(cls) -> aioredis.Redis:
        pool = cls.get_pool()
        return aioredis.Redis(connection_pool=pool)

    @classmethod
    async def close(cls):
        if cls._pool:
            await cls._pool.disconnect()
            cls._pool = None
            logger.info("Redis connection pool closed.")
