import logging
from typing import Dict, Any, Optional
import httpx
from config import settings

logger = logging.getLogger("WhatsAppCloud")

class WhatsAppCloudBroadcaster:
    """
    Broadcaster for official Meta WhatsApp Business Cloud API.
    Used for verified Zero-Ban Channel Mode or Template messaging.
    """
    def __init__(
        self,
        access_token: Optional[str] = None,
        phone_number_id: Optional[str] = None
    ):
        self.access_token = access_token or settings.WHATSAPP_CLOUD_ACCESS_TOKEN
        self.phone_number_id = phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID
        self.api_url = f"https://graph.facebook.com/v19.0/{self.phone_number_id}/messages"

    async def broadcast_deal(self, formatted_data: Dict[str, Any], recipient: Optional[str] = None) -> bool:
        to_number = recipient or settings.WHATSAPP_RECIPIENT_PHONE
        if not self.access_token or not self.phone_number_id or not to_number:
            logger.debug("WhatsApp Cloud API credentials or recipient phone missing. Skipping.")
            return False

        message_body = formatted_data.get("text", "")
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "text",
            "text": {
                "preview_url": True,
                "body": message_body
            }
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(self.api_url, json=payload, headers=headers)
                if resp.status_code in [200, 201]:
                    logger.info(f"Successfully broadcast deal via WhatsApp Cloud API to {to_number}")
                    return True
                else:
                    logger.error(f"WhatsApp Cloud API failed: {resp.text}")
            except Exception as e:
                logger.error(f"WhatsApp Cloud API request error: {e}")

        return False
