import time
import json
import hashlib
import logging
from typing import Optional, Tuple, Dict, Any
import redis.asyncio as aioredis
from config import settings

logger = logging.getLogger("Deduplicator")

class DeduplicationEngine:
    """
    Redis-backed deduplication and historical price tracker.
    Maintains a 6-hour sliding window per product hash and tracks:
    (product_hash, last_seen_price, lowest_price, last_timestamp).
    """
    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self._redis = redis_client
        self.window_seconds = settings.DEDUP_WINDOW_HOURS * 3600
        self.min_drop_percent = settings.MIN_PRICE_DROP_PERCENT

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    @classmethod
    def generate_product_hash(cls, canonical_identifier: str) -> str:
        """
        Generates an MD5/SHA256 hash from a canonical ASIN, product ID, or normalized URL.
        """
        clean_id = canonical_identifier.strip().lower()
        return hashlib.sha256(clean_id.encode('utf-8')).hexdigest()[:16]

    async def evaluate_deal(
        self, 
        product_hash: str, 
        current_price: Optional[float]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Evaluates whether a deal should be broadcast or dropped.
        Returns:
            should_broadcast: bool
            reason: str
            history_data: dict
        """
        if not product_hash:
            return True, "no_product_hash_passthrough", {}

        key = f"deal:history:{product_hash}"
        now = time.time()

        raw_data = await self.redis.get(key)
        
        # New deal (never seen before or expired past sliding window)
        if not raw_data:
            initial_data = {
                "product_hash": product_hash,
                "first_seen_price": current_price,
                "last_seen_price": current_price,
                "lowest_price": current_price,
                "timestamp": now,
                "broadcast_count": 1
            }
            await self.redis.set(key, json.dumps(initial_data), ex=self.window_seconds)
            logger.info(f"New product detected [{product_hash}]: Price={current_price}. Permitted broadcast.")
            return True, "new_deal", initial_data

        history = json.loads(raw_data)
        last_price = history.get("last_seen_price")
        lowest_price = history.get("lowest_price")

        # Price unavailable: suppress if posted within sliding window
        if current_price is None:
            logger.info(f"Duplicate product [{product_hash}] without price info within sliding window. Suppressed.")
            return False, "duplicate_no_price", history

        # If previous price is also unavailable, accept the new one
        if last_price is None:
            history["last_seen_price"] = current_price
            history["lowest_price"] = current_price
            history["timestamp"] = now
            history["broadcast_count"] = history.get("broadcast_count", 0) + 1
            await self.redis.set(key, json.dumps(history), ex=self.window_seconds)
            return True, "price_identified", history

        # Calculate price difference
        if current_price >= last_price:
            # Price is same or higher -> reject as duplicate/jitter
            logger.info(f"Deal rejected for [{product_hash}]: Price {current_price} >= last seen {last_price}")
            return False, f"price_not_lower_{current_price}_vs_{last_price}", history

        # Price has dropped! Check if drop meets threshold
        price_drop = last_price - current_price
        drop_pct = (price_drop / last_price) * 100.0

        is_all_time_low = (lowest_price is None) or (current_price < lowest_price)

        if drop_pct >= self.min_drop_percent or is_all_time_low:
            logger.info(f"Genuine price drop detected for [{product_hash}]: {last_price} -> {current_price} (-{drop_pct:.1f}%). All-time-low: {is_all_time_low}")
            
            history["last_seen_price"] = current_price
            if is_all_time_low:
                history["lowest_price"] = current_price
            history["timestamp"] = now
            history["broadcast_count"] = history.get("broadcast_count", 0) + 1
            
            # Reset sliding window TTL
            await self.redis.set(key, json.dumps(history), ex=self.window_seconds)
            reason = "all_time_low" if is_all_time_low else f"price_drop_{drop_pct:.1f}pct"
            return True, reason, history
        else:
            logger.info(f"Insignificant price drop for [{product_hash}]: -{drop_pct:.1f}% (< {self.min_drop_percent}%). Suppressed.")
            return False, "insignificant_drop", history
