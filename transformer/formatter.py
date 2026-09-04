import html
from typing import Dict, Any, Optional
from ingestion.normalizer import DealPayload

class DealFormatter:
    """
    Formats deal payloads into visually compelling, conversion-optimized
    templates for Telegram and WhatsApp.
    """

    @classmethod
    def get_urgency_badge(cls, deal: DealPayload, drop_reason: Optional[str] = None) -> str:
        if drop_reason == "all_time_low":
            return "🚨 <b>ALL TIME LOW PRICE</b> 🚨"
        if deal.is_flash_or_loot or (deal.discount_percent and deal.discount_percent >= 75):
            return "🔥 <b>LOOT DEAL ALERT</b> 🔥"
        if deal.discount_percent and deal.discount_percent >= 50:
            return "⚡ <b>HEAVY DISCOUNT DROP</b> ⚡"
        return "✨ <b>HOT DEAL</b> ✨"

    @classmethod
    def get_whatsapp_urgency_badge(cls, deal: DealPayload, drop_reason: Optional[str] = None) -> str:
        if drop_reason == "all_time_low":
            return "🚨 *ALL TIME LOW PRICE* 🚨"
        if deal.is_flash_or_loot or (deal.discount_percent and deal.discount_percent >= 75):
            return "🔥 *LOOT DEAL ALERT* 🔥"
        if deal.discount_percent and deal.discount_percent >= 50:
            return "⚡ *HEAVY DISCOUNT DROP* ⚡"
        return "✨ *HOT DEAL* ✨"

    @classmethod
    def format_telegram(cls, deal: DealPayload, drop_reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Formats for Telegram Bot API using HTML parse mode.
        Returns: {"text": str, "inline_keyboard": list}
        """
        badge = cls.get_urgency_badge(deal, drop_reason)
        safe_title = html.escape(deal.title or "Exclusive Online Deal")
        
        lines = [badge, "", f"📦 <b>{safe_title}</b>", ""]

        # Price row
        if deal.current_price:
            curr_str = f"₹{deal.current_price:,.0f}"
            if deal.mrp and deal.mrp > deal.current_price:
                mrp_str = f"₹{deal.mrp:,.0f}"
                pct_str = f"{deal.discount_percent:.0f}%" if deal.discount_percent else ""
                lines.append(f"💰 <b>Deal Price:</b> {curr_str} <s>{mrp_str}</s> ({pct_str} OFF)")
            else:
                lines.append(f"💰 <b>Deal Price:</b> {curr_str}")
        
        platform_name = (deal.platform or "Store").capitalize()
        lines.append(f"🏪 <b>Platform:</b> {platform_name}")

        target_url = deal.monetized_url or (deal.extracted_urls[0] if deal.extracted_urls else "")
        if target_url:
            lines.append("")
            lines.append(f"👉 <b>Buy Here:</b> <a href=\"{target_url}\">Click to Claim Deal</a>")

        lines.append("")
        lines.append("⏳ <i>Prices drop quickly. Grab before out of stock!</i>")

        caption_text = "\n".join(lines)

        inline_keyboard = []
        if target_url:
            inline_keyboard = [
                [{"text": "🛒 BUY NOW", "url": target_url}]
            ]

        return {
            "text": caption_text,
            "parse_mode": "HTML",
            "inline_keyboard": inline_keyboard,
            "image_url": deal.image_url,
            "image_path": deal.image_path
        }

    @classmethod
    def format_whatsapp(cls, deal: DealPayload, drop_reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Formats for WhatsApp using standard WhatsApp text styling.
        """
        badge = cls.get_whatsapp_urgency_badge(deal, drop_reason)
        title = deal.title or "Exclusive Online Deal"
        
        lines = [badge, "", f"*{title}*", ""]

        if deal.current_price:
            curr_str = f"₹{deal.current_price:,.0f}"
            if deal.mrp and deal.mrp > deal.current_price:
                mrp_str = f"₹{deal.mrp:,.0f}"
                pct_str = f"({deal.discount_percent:.0f}% OFF)" if deal.discount_percent else ""
                lines.append(f"💰 *Deal Price:* {curr_str} ~{mrp_str}~ {pct_str}")
            else:
                lines.append(f"💰 *Deal Price:* {curr_str}")

        platform_name = (deal.platform or "Store").capitalize()
        lines.append(f"🏪 *Platform:* {platform_name}")

        target_url = deal.monetized_url or (deal.extracted_urls[0] if deal.extracted_urls else "")
        if target_url:
            lines.append("")
            lines.append(f"🛒 *Buy Link:* {target_url}")

        lines.append("")
        lines.append("_⚡ Hurry, price can jump anytime!_")

        message_text = "\n".join(lines)

        return {
            "text": message_text,
            "image_url": deal.image_url,
            "image_path": deal.image_path,
            "target_url": target_url
        }
