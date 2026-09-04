import sys
import argparse
import asyncio
import logging

from config import settings
from ingestion.normalizer import DealNormalizer, DealPayload
from queue.producer import DealProducer
from queue.worker import DealPipelineWorker
from ingestion.scraper_engine import TargetScraperEngine

logger = logging.getLogger("SastaMaalApp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

async def inject_test_deal():
    """Injects a sample high-discount e-commerce deal to test end-to-end processing."""
    producer = DealProducer()
    sample_text = (
        "🔥 BOAT Rockerz 450 Bluetooth On Ear Headphones with Mic!\n"
        "💰 Deal Price: ₹999 (MRP ₹3,990) - Flat 75% OFF!\n"
        "⚡ All Time Low Price - Limited Stock!\n"
        "🛒 Grab here: https://www.amazon.in/dp/B07PR1CL3S?tag=thirdparty-21&ascsubtag=sample123"
    )
    deal = DealNormalizer.normalize(
        raw_text=sample_text,
        source="manual_test_injector",
        image_url="https://m.media-amazon.com/images/I/61u1VALn6JL._SX679_.jpg"
    )
    logger.info(f"Injecting test deal: {deal.title}")
    success = await producer.enqueue_deal(deal)
    if success:
        logger.info("✅ Successfully injected test deal into Redis queue 'deals:incoming'!")
        logger.info("Start the worker (`python main.py --worker`) to process and broadcast it.")
    else:
        logger.error("❌ Failed to inject deal. Ensure Redis is running.")

async def run_worker():
    logger.info("🚀 Starting Sasta Maal Pipeline Worker...")
    worker = DealPipelineWorker()
    await worker.start()

async def run_scraper():
    logger.info("🔍 Starting Sasta Maal Scraper Engine...")
    scraper = TargetScraperEngine()
    await scraper.start_periodic_scraper()

async def run_all():
    logger.info("🌟 Starting Sasta Maal (Worker + Scraper)...")
    worker = DealPipelineWorker()
    scraper = TargetScraperEngine()
    await asyncio.gather(
        worker.start(),
        scraper.start_periodic_scraper()
    )

def main():
    parser = argparse.ArgumentParser(description="Sasta Maal Deal Aggregator & Broadcast Pipeline Runner")
    parser.add_argument("--worker", action="store_true", help="Run the deal processing and broadcast worker")
    parser.add_argument("--scraper", action="store_true", help="Run the periodic deal scraper engine")
    parser.add_argument("--userbot", action="store_true", help="Run the Telethon Telegram userbot listener")
    parser.add_argument("--test-deal", action="store_true", help="Inject a sample loot deal into Redis")
    parser.add_argument("--all", action="store_true", help="Run worker and scraper concurrently")

    args = parser.parse_args()

    if args.test_deal:
        asyncio.run(inject_test_deal())
    elif args.worker:
        asyncio.run(run_worker())
    elif args.scraper:
        asyncio.run(run_scraper())
    elif args.userbot:
        from ingestion.userbot_listener import UserbotListener
        listener = UserbotListener()
        asyncio.run(listener.start())
    elif args.all:
        asyncio.run(run_all())
    else:
        parser.print_help()
        print("\nQuick Run Examples:")
        print("  python main.py --test-deal    # Push a test deal into the queue")
        print("  python main.py --worker       # Start processing deals")
        print("  python main.py --scraper      # Start scraping Amazon/Flipkart deals")
        print("  python main.py --all          # Start worker and scraper concurrently")

if __name__ == "__main__":
    main()
