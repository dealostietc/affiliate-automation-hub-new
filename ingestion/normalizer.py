import re
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class DealPayload(BaseModel):
    id: Optional[str] = None
    source: str  # e.g., "telethon:channel_name" or "scraper:amazon"
    raw_text: str
    title: Optional[str] = None
    current_price: Optional[float] = None
    mrp: Optional[float] = None
    discount_percent: Optional[float] = None
    extracted_urls: List[str] = Field(default_factory=list)
    monetized_url: Optional[str] = None
    image_url: Optional[str] = None
    image_path: Optional[str] = None
    platform: Optional[str] = None  # "amazon", "flipkart", "myntra", "ajio", etc.
    product_hash: Optional[str] = None
    timestamp: Optional[float] = None
    is_flash_or_loot: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

class DealNormalizer:
    """
    Extracts structured pricing, discounts, titles, and links from raw text/captions.
    """
    # Regex for Indian Rupee prices: ₹999, Rs. 999, Rs 1,499, INR 299, etc.
    PRICE_PATTERN = re.compile(
        r'(?:₹|Rs\.?|INR)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+)', 
        re.IGNORECASE
    )
    
    # Regex for discount percentages: 80% off, Flat 75% OFF, 70% discount
    DISCOUNT_PATTERN = re.compile(
        r'(?:flat\s*)?([0-9]{1,2})\s*%\s*(?:off|discount)?',
        re.IGNORECASE
    )

    # General URL matching pattern (including shortened domains)
    URL_PATTERN = re.compile(
        r'https?://[^\s<>"\')]+',
        re.IGNORECASE
    )

    # Loot / Flash indicators
    LOOT_KEYWORDS = [
        "loot", "price error", "bug", "all time low", "lowest",
        "steal", "flash sale", "lightning deal", "huge drop"
    ]

    @classmethod
    def clean_number(cls, val_str: str) -> float:
        cleaned = val_str.replace(',', '').strip()
        return float(cleaned)

    @classmethod
    def extract_urls(cls, text: str) -> List[str]:
        if not text:
            return []
        matches = cls.URL_PATTERN.findall(text)
        # Clean trailing punctuation from URLs
        cleaned = []
        for url in matches:
            u = url.rstrip('.,;)]}>"')
            if u not in cleaned:
                cleaned.append(u)
        return cleaned

    @classmethod
    def extract_prices(cls, text: str) -> Dict[str, Optional[float]]:
        """
        Parses current price and MRP if both exist (e.g., 'At ₹499 (MRP ₹1999)').
        """
        matches = cls.PRICE_PATTERN.findall(text)
        if not matches:
            return {"current_price": None, "mrp": None}
        
        prices = [cls.clean_number(m) for m in matches if cls.clean_number(m) > 0]
        if not prices:
            return {"current_price": None, "mrp": None}

        # If multiple prices found, lower is usually offer price, higher is MRP
        if len(prices) == 1:
            return {"current_price": prices[0], "mrp": None}
        
        sorted_prices = sorted(prices)
        current = sorted_prices[0]
        mrp = sorted_prices[-1] if sorted_prices[-1] > current else None

        return {"current_price": current, "mrp": mrp}

    @classmethod
    def extract_discount(cls, text: str, current_price: Optional[float] = None, mrp: Optional[float] = None) -> Optional[float]:
        # 1. Look for explicit percentage in text
        match = cls.DISCOUNT_PATTERN.search(text)
        if match:
            try:
                pct = float(match.group(1))
                if 0 < pct < 100:
                    return pct
            except ValueError:
                pass

        # 2. Derive from MRP & current price if available
        if current_price and mrp and mrp > current_price:
            calculated = round(((mrp - current_price) / mrp) * 100, 1)
            return calculated

        return None

    @classmethod
    def extract_title(cls, text: str) -> str:
        lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
        if not lines:
            return "Hot E-Commerce Deal"
        
        # Look for first line that is not purely a link or emoji
        for line in lines:
            cleaned = cls.URL_PATTERN.sub('', line).strip()
            # Remove leading emojis/bullets
            cleaned = re.sub(r'^[^\w\s]+', '', cleaned).strip()
            if len(cleaned) >= 5:
                # Truncate if too long
                return cleaned[:120]
        
        return lines[0][:120]

    @classmethod
    def check_is_loot(cls, text: str, discount_pct: Optional[float] = None) -> bool:
        lower_text = text.lower()
        if any(kw in lower_text for kw in cls.LOOT_KEYWORDS):
            return True
        if discount_pct and discount_pct >= 75.0:
            return True
        return False

    @classmethod
    def normalize(cls, raw_text: str, source: str, image_url: Optional[str] = None, image_path: Optional[str] = None) -> DealPayload:
        urls = cls.extract_urls(raw_text)
        price_info = cls.extract_prices(raw_text)
        current_price = price_info["current_price"]
        mrp = price_info["mrp"]
        discount = cls.extract_discount(raw_text, current_price, mrp)
        title = cls.extract_title(raw_text)
        is_loot = cls.check_is_loot(raw_text, discount)

        return DealPayload(
            source=source,
            raw_text=raw_text,
            title=title,
            current_price=current_price,
            mrp=mrp,
            discount_percent=discount,
            extracted_urls=urls,
            image_url=image_url,
            image_path=image_path,
            is_flash_or_loot=is_loot
        )
