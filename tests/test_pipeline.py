import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

from ingestion.normalizer import DealNormalizer, DealPayload
from transformer.affiliate_engine import AffiliateEngine
from transformer.deduplicator import DeduplicationEngine
from transformer.formatter import DealFormatter

# ----------------------------------------------------------------------
# 1. Normalizer Unit Tests
# ----------------------------------------------------------------------
def test_normalizer_price_extraction():
    text = "🔥 Noise ColorFit Pulse Smartwatch\nPrice: ₹1,499 (MRP: ₹4,999)\nFlat 70% off!\nhttps://amzn.to/3example"
    deal = DealNormalizer.normalize(raw_text=text, source="test_channel")
    
    assert deal.current_price == 1499.0
    assert deal.mrp == 4999.0
    assert deal.discount_percent == 70.0
    assert deal.title == "Noise ColorFit Pulse Smartwatch"
    assert "https://amzn.to/3example" in deal.extracted_urls
    assert deal.is_flash_or_loot is False  # 70% is high, let's test loot trigger below

def test_normalizer_loot_trigger():
    loot_text = "🚨 MASSIVE PRICE ERROR / LOOT DEAL!\nBoat Rockerz 450 at just ₹199 (MRP ₹3,990)!\n85% off\nhttps://amzn.to/boat450"
    deal = DealNormalizer.normalize(raw_text=loot_text, source="loot_channel")

    assert deal.current_price == 199.0
    assert deal.mrp == 3990.0
    assert deal.is_flash_or_loot is True

# ----------------------------------------------------------------------
# 2. Affiliate Engine Unit Tests
# ----------------------------------------------------------------------
def test_amazon_asin_extraction_and_rewrite():
    engine = AffiliateEngine()
    engine.amazon_tag = "mytag-21"

    # Case A: Standard /dp/ URL with third-party tag
    url_a = "https://www.amazon.in/dp/B08N5WRWNW?tag=spammer-21&ascsubtag=12345"
    rewritten_a, asin_a = engine.rewrite_amazon_url(url_a)
    assert asin_a == "B08N5WRWNW"
    assert rewritten_a == "https://www.amazon.in/dp/B08N5WRWNW?tag=mytag-21"

    # Case B: /gp/product/ URL
    url_b = "https://www.amazon.in/gp/product/B09XYZ1234/?ref=ppx_yo_dt_b_search_asin_title"
    rewritten_b, asin_b = engine.rewrite_amazon_url(url_b)
    assert asin_b == "B09XYZ1234"
    assert rewritten_b == "https://www.amazon.in/dp/B09XYZ1234?tag=mytag-21"

@pytest.mark.asyncio
async def test_affiliate_engine_process_url_amazon():
    engine = AffiliateEngine()
    engine.amazon_tag = "sastamaal-21"

    with patch.object(engine, "unshorten_url", new=AsyncMock(return_value="https://www.amazon.in/dp/B07HG8S7KP?tag=old-21")):
        result = await engine.process_url("https://amzn.to/test1234")
        assert result["platform"] == "amazon"
        assert result["canonical_id"] == "amazon:B07HG8S7KP"
        assert result["monetized_url"] == "https://www.amazon.in/dp/B07HG8S7KP?tag=sastamaal-21"

# ----------------------------------------------------------------------
# 3. Deduplicator Unit Tests
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_deduplicator_new_deal():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # Key does not exist in Redis

    dedup = DeduplicationEngine(redis_client=mock_redis)
    product_hash = DeduplicationEngine.generate_product_hash("amazon:B08N5WRWNW")

    should_broadcast, reason, history = await dedup.evaluate_deal(product_hash, 999.0)
    assert should_broadcast is True
    assert reason == "new_deal"
    assert mock_redis.set.called

@pytest.mark.asyncio
async def test_deduplicator_rejects_identical_price_within_window():
    mock_redis = AsyncMock()
    cached_history = {
        "product_hash": "testhash",
        "last_seen_price": 999.0,
        "lowest_price": 999.0,
        "timestamp": 100000.0,
        "broadcast_count": 1
    }
    mock_redis.get.return_value = json.dumps(cached_history)

    dedup = DeduplicationEngine(redis_client=mock_redis)
    # Incoming deal with same price 999.0
    should_broadcast, reason, history = await dedup.evaluate_deal("testhash", 999.0)
    assert should_broadcast is False
    assert "price_not_lower" in reason

@pytest.mark.asyncio
async def test_deduplicator_accepts_significant_price_drop():
    mock_redis = AsyncMock()
    cached_history = {
        "product_hash": "testhash",
        "last_seen_price": 1000.0,
        "lowest_price": 1000.0,
        "timestamp": 100000.0,
        "broadcast_count": 1
    }
    mock_redis.get.return_value = json.dumps(cached_history)

    dedup = DeduplicationEngine(redis_client=mock_redis)
    # Price dropped from 1000 to 800 (20% drop, > 5%)
    should_broadcast, reason, history = await dedup.evaluate_deal("testhash", 800.0)
    assert should_broadcast is True
    assert "all_time_low" in reason or "price_drop" in reason

# ----------------------------------------------------------------------
# 4. Formatter Unit Tests
# ----------------------------------------------------------------------
def test_telegram_formatter():
    deal = DealPayload(
        source="test",
        raw_text="Sample text",
        title="Puma Men's Running Shoes",
        current_price=1299.0,
        mrp=3999.0,
        discount_percent=68.0,
        platform="amazon",
        monetized_url="https://www.amazon.in/dp/B08XYZ?tag=sastamaal-21"
    )

    formatted = DealFormatter.format_telegram(deal)
    assert "Puma Men&#x27;s Running Shoes" in formatted["text"]
    assert "₹1,299" in formatted["text"]
    assert "68% OFF" in formatted["text"]
    assert formatted["parse_mode"] == "HTML"
    assert len(formatted["inline_keyboard"]) == 1
    assert formatted["inline_keyboard"][0][0]["url"] == deal.monetized_url

def test_whatsapp_formatter():
    deal = DealPayload(
        source="test",
        raw_text="Sample text",
        title="Sony WH-1000XM5",
        current_price=24990.0,
        mrp=34990.0,
        discount_percent=29.0,
        platform="amazon",
        monetized_url="https://www.amazon.in/dp/B09XS?tag=sastamaal-21"
    )

    formatted = DealFormatter.format_whatsapp(deal)
    assert "*Sony WH-1000XM5*" in formatted["text"]
    assert "₹24,990" in formatted["text"]
    assert formatted["target_url"] == deal.monetized_url
