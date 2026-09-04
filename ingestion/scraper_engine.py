import os
import random
import asyncio
import logging
from typing import List, Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

from config import settings
from ingestion.normalizer import DealPayload, DealNormalizer
from queue.producer import DealProducer

logger = logging.getLogger("TargetScraper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

class TargetScraperEngine:
    """
    Engine B: Target Scrapers & Mobile Endpoint Ingestion.
    Scrapes high-discount items (>= 70% discount) from Amazon, Flipkart, Myntra, Ajio
    using mobile headers, user-agent rotation, proxy integration, and rate-limiting backoff.
    """
    def __init__(self, proxy_url: Optional[str] = None):
        self.proxy_url = proxy_url or settings.PROXY_URL or None
        self.ua = UserAgent()
        self.producer = DealProducer()
        self.min_discount = settings.SCRAPER_MIN_DISCOUNT_PERCENT

        # Mobile app headers spoofing Android/iOS clients
        self.mobile_headers_pool = [
            {
                "User-Agent": "com.amazon.mShop.android.shopping/28.8.0.100 (Android 14; Mobile; en_IN)",
                "x-amz-rid": "MOCK_RID_12345",
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
            },
            {
                "User-Agent": "Flipkart/7.62 (Android 13; Scale/3.0; Model/Pixel 7)",
                "X-Platform": "android",
                "X-User-Agent": "Android App 7.62",
                "Accept-Language": "en-IN,en;q=0.9",
            },
            {
                "User-Agent": "Myntra/4.52.1 (iPhone; iOS 17.4; Scale/3.00)",
                "X-Client-Platform": "iOS",
                "Accept-Language": "en-IN,en-US;q=0.9",
            }
        ]

    def get_random_headers(self) -> Dict[str, str]:
        headers = random.choice(self.mobile_headers_pool).copy()
        headers["User-Agent"] = self.ua.random
        return headers

    async def fetch_page(self, client: httpx.AsyncClient, url: str) -> Optional[str]:
        headers = self.get_random_headers()
        try:
            response = await client.get(url, headers=headers, follow_redirects=True, timeout=15.0)
            if response.status_code == 200:
                return response.text
            elif response.status_code in [429, 503]:
                logger.warning(f"Rate limited (Status {response.status_code}) on {url}. Applying exponential backoff.")
                await asyncio.sleep(random.uniform(5.0, 12.0))
            else:
                logger.warning(f"Failed to fetch {url}, status code: {response.status_code}")
        except httpx.RequestError as exc:
            logger.error(f"Network error while fetching {url}: {exc}")
        return None

    async def scrape_amazon_lightning_deals(self, client: httpx.AsyncClient) -> List[DealPayload]:
        """
        Scrapes Amazon India Today's Deals / Lightning deals.
        Filters for items having >= min_discount%.
        """
        deals = []
        # Target lightning deals URL
        url = "https://www.amazon.in/gp/goldbox"
        html = await self.fetch_page(client, url)
        if not html:
            return deals

        soup = BeautifulSoup(html, "html.parser")
        # Parse product cards
        items = soup.select("div[data-testid='grid-deals-container'] div[class*='DealGridItem'], div.a-section.dealContainer")
        for item in items[:15]:
            try:
                title_elem = item.select_one("span.a-truncate-full, div[class*='dealTitle'], a[class*='a-link-normal'] span")
                price_elem = item.select_one("span.a-price span.a-offscreen, span[class*='dealPrice']")
                badge_elem = item.select_one("span[class*='dealBadge'], div[class*='badge-percent']")
                link_elem = item.select_one("a[class*='a-link-normal']")
                img_elem = item.select_one("img")

                if not (title_elem and link_elem):
                    continue

                title = title_elem.get_text(strip=True)
                href = link_elem.get("href", "")
                if href.startswith("/"):
                    href = "https://www.amazon.in" + href
                
                price_text = price_elem.get_text(strip=True) if price_elem else ""
                badge_text = badge_elem.get_text(strip=True) if badge_elem else ""
                img_url = img_elem.get("src") if img_elem else None

                raw_text = f"🔥 {title}\n💰 Price: {price_text} ({badge_text})\n👉 {href}"
                normalized = DealNormalizer.normalize(
                    raw_text=raw_text,
                    source="scraper:amazon_lightning",
                    image_url=img_url
                )

                if normalized.discount_percent and normalized.discount_percent >= self.min_discount:
                    deals.append(normalized)
                elif "loot" in title.lower() or "deal" in badge_text.lower():
                    deals.append(normalized)
            except Exception as e:
                logger.debug(f"Error parsing Amazon deal item: {e}")

        logger.info(f"Scraped {len(deals)} qualifying Amazon deals (>={self.min_discount}% off)")
        return deals

    async def scrape_flipkart_flash_deals(self, client: httpx.AsyncClient) -> List[DealPayload]:
        """
        Scrapes Flipkart top offers / clearance deals.
        """
        deals = []
        url = "https://www.flipkart.com/offers-store"
        html = await self.fetch_page(client, url)
        if not html:
            return deals

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div._1AtVbE, div._37K3-p, div[class*='deal-card']")
        for card in cards[:15]:
            try:
                title_elem = card.select_one("div._4rR01T, a.s1Q9rs, div._2WkVRV")
                price_elem = card.select_one("div._30jeq3")
                discount_elem = card.select_one("div._3Ay6Sb span")
                link_elem = card.select_one("a[href*='/p/']")
                img_elem = card.select_one("img")

                if not (title_elem and link_elem):
                    continue

                title = title_elem.get_text(strip=True)
                href = link_elem.get("href", "")
                if href.startswith("/"):
                    href = "https://www.flipkart.com" + href

                price_text = price_elem.get_text(strip=True) if price_elem else ""
                discount_text = discount_elem.get_text(strip=True) if discount_elem else ""
                img_url = img_elem.get("src") if img_elem else None

                raw_text = f"⚡ Flipkart Loot: {title}\n🏷️ Deal Price: {price_text} ({discount_text})\n🛒 Link: {href}"
                normalized = DealNormalizer.normalize(
                    raw_text=raw_text,
                    source="scraper:flipkart_deals",
                    image_url=img_url
                )

                if (normalized.discount_percent and normalized.discount_percent >= self.min_discount) or normalized.is_flash_or_loot:
                    deals.append(normalized)
            except Exception as e:
                logger.debug(f"Error parsing Flipkart card: {e}")

        logger.info(f"Scraped {len(deals)} qualifying Flipkart deals (>={self.min_discount}% off)")
        return deals

    async def run_scrape_cycle(self):
        """Runs a complete scraping cycle across all target endpoints and enqueues deals."""
        logger.info("Initiating scheduled scraping cycle across target platforms...")
        proxies = {"all://": self.proxy_url} if self.proxy_url else None
        transport = httpx.AsyncHTTPTransport(retries=2)

        async with httpx.AsyncClient(proxy=self.proxy_url, transport=transport, timeout=20.0) as client:
            amazon_deals = await self.scrape_amazon_lightning_deals(client)
            await asyncio.sleep(random.uniform(3.0, 7.0))  # Anti-ban delay
            flipkart_deals = await self.scrape_flipkart_flash_deals(client)

            all_deals = amazon_deals + flipkart_deals
            for deal in all_deals:
                await self.producer.enqueue_deal(deal)

        logger.info(f"Scrape cycle complete. Enqueued {len(all_deals)} high-discount deals.")

    async def start_periodic_scraper(self, interval_seconds: int = None):
        interval = interval_seconds or settings.SCRAPER_POLL_INTERVAL_SECONDS
        logger.info(f"Starting Scraper Ingestion Engine with {interval}s poll interval...")
        while True:
            try:
                await self.run_scrape_cycle()
            except Exception as e:
                logger.error(f"Scraper cycle error: {e}", exc_info=True)
            
            # Randomized jitter interval to avoid robotic fingerprinting
            jitter = random.uniform(-15.0, 30.0)
            sleep_duration = max(30.0, interval + jitter)
            logger.info(f"Sleeping for {sleep_duration:.1f}s until next scrape cycle...")
            await asyncio.sleep(sleep_duration)

if __name__ == "__main__":
    engine = TargetScraperEngine()
    try:
        asyncio.run(engine.start_periodic_scraper())
    except KeyboardInterrupt:
        logger.info("Scraper engine terminated by user.")
