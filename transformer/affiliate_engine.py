import re
import logging
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from typing import Optional, Tuple, Dict, Any
import httpx
from config import settings

logger = logging.getLogger("AffiliateEngine")

class AffiliateEngine:
    """
    Transforms raw/shortened e-commerce links into canonical URLs
    and replaces tracking parameters with user-defined affiliate IDs.
    """
    # Shortened domains that require recursive unshortening
    SHORTENED_DOMAINS = {
        "amzn.to", "bit.ly", "fkrt.it", "cutt.ly", "tinyurl.com",
        "t.co", "rb.gy", "myntr.it", "ajio.co", "ern.li", "clnk.in"
    }

    # Regex for Amazon ASIN (10-character alphanumeric starting with B0 or 9-10 digits/letters)
    AMAZON_ASIN_REGEX = re.compile(
        r'/(?:dp|gp/product|gp/aw/d|product-reviews)/([A-Z0-9]{10})',
        re.IGNORECASE
    )

    # Flipkart FSN / Product ID pattern
    FLIPKART_PID_REGEX = re.compile(
        r'pid=([A-Z0-9]{16})',
        re.IGNORECASE
    )

    def __init__(self):
        self.amazon_tag = settings.AMAZON_ASSOCIATE_TAG
        self.earnkaro_key = settings.EARNKARO_API_KEY
        self.earnkaro_url = settings.EARNKARO_API_URL
        self.cuelinks_key = settings.CUELINKS_API_KEY
        self.cuelinks_channel = settings.CUELINKS_CHANNEL_ID
        self.cuelinks_url = settings.CUELINKS_API_URL

    async def unshorten_url(self, url: str, max_redirects: int = 8) -> str:
        """
        Recursively follows HTTP 301/302/307 redirects to discover
        the true destination canonical URL.
        """
        current_url = url
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
        }

        async with httpx.AsyncClient(follow_redirects=False, timeout=10.0) as client:
            for hop in range(max_redirects):
                parsed = urlparse(current_url)
                # If domain is not in shortened list and looks like canonical product page, stop early
                if parsed.netloc.lower() not in self.SHORTENED_DOMAINS and any(
                    marker in current_url for marker in ["/dp/", "pid=", "/p/", "/buy/"]
                ):
                    break

                try:
                    # Head request first, fallback to GET if 405 Method Not Allowed
                    resp = await client.head(current_url, headers=headers)
                    if resp.status_code in [405, 403]:
                        resp = await client.get(current_url, headers=headers)
                    
                    if resp.status_code in [301, 302, 303, 307, 308]:
                        location = resp.headers.get("Location")
                        if not location:
                            break
                        if location.startswith("/"):
                            # Relative redirect
                            current_url = f"{parsed.scheme}://{parsed.netloc}{location}"
                        else:
                            current_url = location
                    else:
                        break
                except Exception as e:
                    logger.debug(f"Redirect resolution interrupted at {current_url}: {e}")
                    break

        return current_url

    def rewrite_amazon_url(self, canonical_url: str) -> Tuple[str, str]:
        """
        Extracts ASIN from Amazon URL, discards third-party affiliate query parameters,
        and injects user's Associate tag.
        Returns (monetized_url, canonical_asin)
        """
        match = self.AMAZON_ASIN_REGEX.search(canonical_url)
        if not match:
            # Fallback: clean query params and attach tag
            parsed = urlparse(canonical_url)
            qs = parse_qs(parsed.query)
            qs['tag'] = [self.amazon_tag]
            for param in ['ascsubtag', 'linkCode', 'ref', 'ref_']:
                qs.pop(param, None)
            new_query = urlencode(qs, doseq=True)
            monetized = urlunparse(parsed._replace(query=new_query))
            return monetized, canonical_url

        asin = match.group(1).upper()
        clean_url = f"https://www.amazon.in/dp/{asin}?tag={self.amazon_tag}"
        return clean_url, asin

    async def monetize_with_earnkaro(self, client: httpx.AsyncClient, target_url: str) -> Optional[str]:
        """Generates an affiliate tracking link via EarnKaro API."""
        if not self.earnkaro_key:
            return None

        payload = {
            "api_key": self.earnkaro_key,
            "urls": [target_url]
        }
        try:
            resp = await client.post(self.earnkaro_url, json=payload, timeout=8.0)
            if resp.status_code == 200:
                data = resp.json()
                # Format: {"status": "success", "data": [{"deal_url": "..."}]}
                if data.get("status") == "success" and data.get("data"):
                    return data["data"][0].get("deal_url")
        except Exception as e:
            logger.warning(f"EarnKaro API error: {e}")
        return None

    async def monetize_with_cuelinks(self, client: httpx.AsyncClient, target_url: str) -> Optional[str]:
        """Generates an affiliate tracking link via Cuelinks API."""
        if not self.cuelinks_key:
            return None

        headers = {
            "Authorization": f"Token token={self.cuelinks_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "url": target_url,
            "channel_id": self.cuelinks_channel
        }
        try:
            resp = await client.post(self.cuelinks_url, json=payload, headers=headers, timeout=8.0)
            if resp.status_code in [200, 201]:
                data = resp.json()
                if "affiliate_url" in data:
                    return data["affiliate_url"]
        except Exception as e:
            logger.warning(f"Cuelinks API error: {e}")
        return None

    async def process_url(self, raw_url: str) -> Dict[str, Any]:
        """
        Main pipeline entry point for URL transformation:
        1. Resolves shortened links.
        2. Detects platform (Amazon, Flipkart, Myntra, Ajio, or generic).
        3. Extracts canonical identifier (ASIN, PID, slug).
        4. Injects affiliate tag or calls aggregator API.
        """
        resolved_url = await self.unshorten_url(raw_url)
        parsed = urlparse(resolved_url)
        hostname = parsed.netloc.lower()

        platform = "generic"
        canonical_id = resolved_url
        monetized_url = resolved_url

        # 1. Amazon
        if "amazon." in hostname or "amzn." in hostname:
            platform = "amazon"
            monetized_url, asin = self.rewrite_amazon_url(resolved_url)
            canonical_id = f"amazon:{asin}"

        # 2. Flipkart
        elif "flipkart." in hostname or "fkrt." in hostname:
            platform = "flipkart"
            pid_match = self.FLIPKART_PID_REGEX.search(resolved_url)
            if pid_match:
                canonical_id = f"flipkart:{pid_match.group(1).upper()}"
            else:
                canonical_id = f"flipkart:{parsed.path}"

            # Strip existing tracking parameters
            clean_url = urlunparse(parsed._replace(query=""))
            # Monetize via Aggregator
            async with httpx.AsyncClient() as client:
                m_link = await self.monetize_with_earnkaro(client, clean_url)
                if not m_link:
                    m_link = await self.monetize_with_cuelinks(client, clean_url)
                monetized_url = m_link or clean_url

        # 3. Myntra / Ajio
        elif any(store in hostname for store in ["myntra.", "ajio."]):
            platform = "myntra" if "myntra." in hostname else "ajio"
            canonical_id = f"{platform}:{parsed.path}"
            clean_url = urlunparse(parsed._replace(query=""))
            
            async with httpx.AsyncClient() as client:
                m_link = await self.monetize_with_earnkaro(client, clean_url)
                if not m_link:
                    m_link = await self.monetize_with_cuelinks(client, clean_url)
                monetized_url = m_link or clean_url

        return {
            "original_url": raw_url,
            "resolved_url": resolved_url,
            "monetized_url": monetized_url,
            "platform": platform,
            "canonical_id": canonical_id
        }
