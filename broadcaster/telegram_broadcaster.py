import os
import asyncio
import logging
from typing import Dict, Any, Optional
import httpx
from config import settings

logger = logging.getLogger("TelegramBroadcaster")

class TelegramBroadcaster:
    """
    Official Telegram Bot API broadcaster with photo cards,
    HTML captions, and inline CTA buttons.
    """
    def __init__(self, bot_token: Optional[str] = None, channel_id: Optional[str] = None):
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.channel_id = channel_id or settings.TELEGRAM_BROADCAST_CHANNEL_ID
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"

    async def broadcast_deal(self, formatted_data: Dict[str, Any]) -> bool:
        if not self.bot_token or not self.channel_id:
            logger.warning("Telegram Bot Token or Channel ID not configured. Skipping broadcast.")
            return False

        caption = formatted_data.get("text", "")
        inline_keyboard = formatted_data.get("inline_keyboard", [])
        image_url = formatted_data.get("image_url")
        image_path = formatted_data.get("image_path")

        reply_markup = {"inline_keyboard": inline_keyboard} if inline_keyboard else None

        async with httpx.AsyncClient(timeout=20.0) as client:
            # 1. Attempt sending photo with caption if media exists
            if image_path and os.path.exists(image_path):
                try:
                    with open(image_path, "rb") as f:
                        files = {"photo": f}
                        data = {
                            "chat_id": self.channel_id,
                            "caption": caption,
                            "parse_mode": "HTML"
                        }
                        if reply_markup:
                            import json
                            data["reply_markup"] = json.dumps(reply_markup)
                        
                        resp = await client.post(f"{self.api_base}/sendPhoto", data=data, files=files)
                        if resp.status_code == 200:
                            logger.info(f"Successfully posted photo deal to Telegram: {self.channel_id}")
                            return True
                        else:
                            logger.warning(f"Telegram sendPhoto (local) failed: {resp.text}")
                except Exception as e:
                    logger.error(f"Error sending local photo to Telegram: {e}")

            elif image_url and image_url.startswith("http"):
                try:
                    payload = {
                        "chat_id": self.channel_id,
                        "photo": image_url,
                        "caption": caption,
                        "parse_mode": "HTML"
                    }
                    if reply_markup:
                        payload["reply_markup"] = reply_markup
                    
                    resp = await client.post(f"{self.api_base}/sendPhoto", json=payload)
                    if resp.status_code == 200:
                        logger.info(f"Successfully posted photo deal to Telegram: {self.channel_id}")
                        return True
                    else:
                        logger.warning(f"Telegram sendPhoto (URL) failed: {resp.text}")
                except Exception as e:
                    logger.error(f"Error sending photo URL to Telegram: {e}")

            # 2. Fallback to standard sendMessage
            try:
                payload = {
                    "chat_id": self.channel_id,
                    "text": caption,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False
                }
                if reply_markup:
                    payload["reply_markup"] = reply_markup

                resp = await client.post(f"{self.api_base}/sendMessage", json=payload)
                if resp.status_code == 200:
                    logger.info(f"Successfully posted text deal to Telegram: {self.channel_id}")
                    return True
                elif resp.status_code == 429:
                    retry_after = resp.json().get("parameters", {}).get("retry_after", 10)
                    logger.warning(f"Telegram rate limited! Waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    # Retry once
                    await client.post(f"{self.api_base}/sendMessage", json=payload)
                    return True
                else:
                    logger.error(f"Telegram sendMessage failed: {resp.text}")
            except Exception as e:
                logger.error(f"Telegram broadcast error: {e}")

        return False
