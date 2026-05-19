# backend/app/notifications/telegram.py
#
# PURPOSE: The ONLY file that talks to Telegram's Bot API
#
# ANALOGY: This is your "phone" — it knows how to dial Telegram
# and send a message. It knows nothing about what the message
# means or why it's being sent — that's the notifier's job.
#
# WHY KEEP THIS SEPARATE FROM notifier.py?
# If Telegram changes their API tomorrow, we update ONE file.
# If we want to add WhatsApp later, we create whatsapp.py
# and plug it into notifier.py. Nothing else changes.


import sys
import os
import json
import logging
import urllib.request
import urllib.error
from typing import Optional

sys.path.append(
    os.path.join(os.path.dirname(__file__), '..', '..', '..')
)
from app.core.config import settings

logger = logging.getLogger(__name__)

# Telegram message length limit is 4096 characters
# We truncate to stay safely under that limit
MAX_MESSAGE_LENGTH = 4000


class TelegramNotifier:
    """
    Sends messages to Telegram using the Bot API.

    WHY NOT USE A TELEGRAM LIBRARY?
    Libraries like python-telegram-bot are great for complex bots
    but overkill for sending simple alerts. Using urllib (built-in)
    means one less dependency and full control over the HTTP call.
    We already understand how this works from our test file.

    WHY A CLASS INSTEAD OF FUNCTIONS?
    The bot token and chat ID are always needed together.
    Storing them in __init__ means we never pass them as
    parameters — they're always available as self.token etc.
    Also makes it easy to mock in tests.
    """

    # Telegram Bot API base URL
    # All API calls go to this URL + method name
    BASE_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self):
        self.token   = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID

        # Validate at startup — fail fast if misconfigured
        if not self.token or not self.chat_id:
            logger.warning(
                "Telegram credentials missing — notifications disabled. "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env"
            )
            self.enabled = False
        else:
            self.enabled = True
            logger.info("Telegram notifier initialised")

    def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """
        Sends a plain message to your Telegram chat.

        PARAMETERS:
        message:    The text to send. Supports HTML formatting:
                    <b>bold</b>, <i>italic</i>, <code>monospace</code>
        parse_mode: "HTML" or "Markdown" — how to interpret formatting

        RETURNS: True if sent successfully, False if failed

        WHY RETURN BOOL INSTEAD OF RAISING EXCEPTION?
        Notification failures should never crash the main system.
        If Telegram is down, we log the error and continue.
        The order is still saved to the database — that's what matters.
        Losing an alert is bad. Losing an order record is worse.

        RETRY LOGIC:
        We attempt up to 2 retries on failure with a short delay.
        Telegram occasionally has transient errors (5xx responses).
        Retrying handles these without manual intervention.
        """
        if not self.enabled:
            logger.debug("Telegram disabled — skipping notification")
            return False

        # Truncate if too long — Telegram rejects messages over 4096 chars
        if len(message) > MAX_MESSAGE_LENGTH:
            message = message[:MAX_MESSAGE_LENGTH] + "\n...[truncated]"

        url = self.BASE_URL.format(
            token=self.token,
            method="sendMessage"
        )

        payload = {
            "chat_id":    self.chat_id,
            "text":       message,
            "parse_mode": parse_mode,
        }

        # Try up to 3 times (1 attempt + 2 retries)
        for attempt in range(3):
            try:
                data = json.dumps(payload).encode("utf-8")
                req  = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"}
                )

                with urllib.request.urlopen(req, timeout=10) as resp:
                    # timeout=10 means give up after 10 seconds
                    # Without timeout, a hung connection blocks forever
                    result = json.loads(resp.read().decode("utf-8"))

                if result.get("ok"):
                    logger.info(
                        f"Telegram message sent (attempt {attempt + 1})"
                    )
                    return True
                else:
                    logger.error(
                        f"Telegram API error: {result.get('description')}"
                    )

            except urllib.error.HTTPError as e:
                logger.error(f"Telegram HTTP error: {e.code} {e.reason}")
                if e.code == 429:
                    # 429 = Too Many Requests — Telegram is rate limiting us
                    # Wait longer before retrying
                    import time
                    time.sleep(5)

            except urllib.error.URLError as e:
                # URLError = network problem (no internet, DNS failure etc)
                logger.error(f"Telegram network error: {e.reason}")

            except Exception as e:
                logger.error(f"Telegram unexpected error: {e}")

            # Wait before retry (exponential backoff)
            # Attempt 0: no wait, Attempt 1: 2s, Attempt 2: 4s
            if attempt < 2:
                import time
                time.sleep(2 ** attempt)

        logger.error("Telegram: all 3 attempts failed")
        return False

    def send_order_alert(self, order_data: dict) -> bool:
        """
        Sends a formatted order notification.

        Formats the raw order dictionary into a readable
        Telegram message with emoji for quick scanning.

        WHY FORMAT HERE?
        The notifier.py knows WHAT to send (an order alert).
        This method knows HOW to format it for Telegram.
        Separation of what vs how.
        """
        platform = order_data.get("platform", "unknown").upper()
        platform_emoji = {
            "ETSY":    "🛍️",
            "EBAY":    "🔨",
            "WEBSITE": "🌐"
        }.get(platform, "🛒")

        message = (
            f"{platform_emoji} <b>New {platform} Order!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Item:</b> {order_data.get('product_name', 'Unknown')}\n"
            f"💰 <b>Sale:</b> ${order_data.get('sale_price', 0):.2f}\n"
            f"💵 <b>Net:</b> ${order_data.get('net_revenue', 0):.2f} "
            f"(after fees)\n"
            f"👤 <b>Buyer:</b> {order_data.get('buyer_name', 'Unknown')}\n"
            f"📍 <b>Ships to:</b> "
            f"{order_data.get('shipping_city', '')} "
            f"{order_data.get('shipping_country', '')}\n"
            f"🔖 <b>Order:</b> #{order_data.get('order_id', 'N/A')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>Fee: ${order_data.get('platform_fee', 0):.2f}</i>"
        )
        return self.send(message)

    def send_message_alert(self, message_data: dict) -> bool:
        """Sends a formatted buyer message notification."""
        platform = message_data.get("platform", "unknown").upper()

        message = (
            f"💬 <b>New {platform} Message!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>From:</b> {message_data.get('buyer_name', 'Unknown')}\n"
            f"📝 <b>Preview:</b> "
            f"{message_data.get('preview', 'No preview')[:150]}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>Reply in your {platform} inbox</i>"
        )
        return self.send(message)

    def send_low_stock_alert(
        self,
        product_name: str,
        platform: str,
        stock_qty: int
    ) -> bool:
        """Sends a low stock warning."""
        message = (
            f"⚠️ <b>Low Stock Alert!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Product:</b> {product_name}\n"
            f"🏪 <b>Platform:</b> {platform.upper()}\n"
            f"🔢 <b>Stock:</b> {stock_qty} unit(s) remaining\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>⚡ Add more stock soon!</i>"
        )
        return self.send(message)

    def send_system_alert(self, title: str, detail: str) -> bool:
        """
        Sends a system/error alert to yourself.
        Used when polling fails or something goes wrong.

        WHY SEND SYSTEM ERRORS TO TELEGRAM?
        This replaces a full alerting system like PagerDuty.
        If polling fails 3 times in a row, you get a Telegram
        message immediately rather than discovering it hours later.

        INTERVIEW POINT:
        "I implemented self-healing alerts — if the polling
         service fails repeatedly, it sends a Telegram alert
         to the operator (me) so issues are caught immediately
         rather than discovered when a buyer complains."
        """
        message = (
            f"🔴 <b>System Alert: {title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<code>{detail[:500]}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>Check logs for details</i>"
        )
        return self.send(message)