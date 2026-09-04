import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Telethon Ingestion (Engine A)
    TELEGRAM_API_ID: int = 0
    TELEGRAM_API_HASH: str = ""
    TELEGRAM_SESSION_NAME: str = "sasta_maal_userbot"
    SOURCE_CHANNELS_RAW: str = Field(default="@deals_sample", alias="SOURCE_CHANNELS")

    # Scraper Ingestion (Engine B)
    PROXY_URL: str = ""
    SCRAPER_MIN_DISCOUNT_PERCENT: int = 70
    SCRAPER_POLL_INTERVAL_SECONDS: int = 300

    # Deduplication & Quality Engine
    DEDUP_WINDOW_HOURS: int = 6
    MIN_PRICE_DROP_PERCENT: float = 5.0

    # Affiliate Engine
    AMAZON_ASSOCIATE_TAG: str = "sastamaal-21"
    EARNKARO_API_KEY: str = ""
    EARNKARO_API_URL: str = "https://api.earnkaro.com/v1/tools/make-links"
    CUELINKS_API_KEY: str = ""
    CUELINKS_CHANNEL_ID: str = ""
    CUELINKS_API_URL: str = "https://api.cuelinks.com/v2/links.json"

    # Telegram Broadcast
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_BROADCAST_CHANNEL_ID: str = ""

    # WhatsApp Broadcast
    WHATSAPP_MODE: str = "baileys"
    WHATSAPP_BAILEYS_ENDPOINT: str = "http://localhost:3001/send-deal"
    WHATSAPP_GROUP_JIDS_RAW: str = Field(default="", alias="WHATSAPP_GROUP_JIDS")
    WHATSAPP_CLOUD_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_RECIPIENT_PHONE: str = ""

    @property
    def source_channels(self) -> List[str]:
        if not self.SOURCE_CHANNELS_RAW:
            return []
        return [ch.strip() for ch in self.SOURCE_CHANNELS_RAW.split(",") if ch.strip()]

    @property
    def whatsapp_group_jids(self) -> List[str]:
        if not self.WHATSAPP_GROUP_JIDS_RAW:
            return []
        return [jid.strip() for jid in self.WHATSAPP_GROUP_JIDS_RAW.split(",") if jid.strip()]

settings = Settings()
