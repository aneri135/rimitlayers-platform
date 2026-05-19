# backend/app/notifications/notifier.py
#
# PURPOSE: Single interface for all notifications
#
# ANALOGY: This is a "notification manager" like on your phone.
# Your phone has one notification centre that receives alerts
# from all apps. Our Notifier is the same — one place that
# receives "send an alert" requests and routes them to the
# right channels (Telegram, email, or both).
#
# THE FACADE PATTERN:
# This is a classic Facade pattern — a simple interface over
# a complex subsystem. The rest of the application doesn't
# know or care about Telegram, SMTP, HTML formatting, or retry
# logic. It just calls notifier.order_received(order_data).


import sys
import os
import logging
from typing import Dict, Optional
from datetime import datetime

sys.path.append(
    os.path.join(os.path.dirname(__file__), '..', '..', '..')
)
from app.notifications.telegram import TelegramNotifier
from app.notifications.email_alert import EmailAlerter

logger = logging.getLogger(__name__)


class Notifier:
    """
    Central notification service.

    Orchestrates all alert channels. Every method here:
    1. Sends via Telegram
    2. Sends via email
    3. Logs what happened
    4. Returns True only if at least one channel succeeded

    WHY "AT LEAST ONE" NOT "ALL"?
    If Telegram is down but email works — you still got the alert.
    Requiring both to succeed would cause false "failure" reports
    when one channel has a transient issue.
    This is called "best effort" delivery for non-critical alerts.
    """

    def __init__(self):
        # Initialise both channels
        # If either fails to init (missing credentials etc),
        # it sets self.enabled = False and logs a warning
        self.telegram = TelegramNotifier()
        self.email    = EmailAlerter()

        # Track notification statistics
        # Used by Prometheus metrics endpoint later
        self.stats = {
            "total_sent":    0,
            "telegram_sent": 0,
            "email_sent":    0,
            "failures":      0,
        }

        logger.info("Notifier initialised with Telegram + Email channels")

    def order_received(self, order_data: Dict) -> bool:
        """
        Called when a new order is detected.
        Sends alert via both Telegram and email.

        USAGE (from email parser or CSV importer):
            notifier.order_received({
                "platform":     "etsy",
                "product_name": "Custom Lithophane",
                "sale_price":   54.99,
                "net_revenue":  44.20,
                "buyer_name":   "Deepanshu M.",
                ...
            })
        """
        platform = order_data.get("platform", "unknown").upper()
        product  = order_data.get("product_name", "Unknown")
        price    = order_data.get("sale_price", 0)

        logger.info(
            f"Sending order alert: {platform} | {product} | ${price}"
        )

        telegram_ok = self.telegram.send_order_alert(order_data)
        email_ok    = self.email.send_order_alert(order_data)

        return self._record_result(
            "order_alert",
            telegram_ok,
            email_ok
        )

    def message_received(self, message_data: Dict) -> bool:
        """
        Called when a new buyer message is detected.

        USAGE:
            notifier.message_received({
                "platform":   "etsy",
                "buyer_name": "Sarah K.",
                "preview":    "Can I get a larger size?",
            })
        """
        buyer    = message_data.get("buyer_name", "Unknown")
        platform = message_data.get("platform", "unknown").upper()

        logger.info(
            f"Sending message alert: {platform} message from {buyer}"
        )

        telegram_ok = self.telegram.send_message_alert(message_data)
        email_ok    = self.email.send_message_alert(message_data)

        return self._record_result(
            "message_alert",
            telegram_ok,
            email_ok
        )

    def low_stock_warning(
        self,
        product_name: str,
        platform: str,
        stock_qty: int
    ) -> bool:
        """
        Called when inventory reaches the low stock threshold.

        USAGE:
            notifier.low_stock_warning(
                "Custom LED Lithophane",
                "etsy",
                1
            )
        """
        logger.warning(
            f"Low stock: {product_name} on {platform} — {stock_qty} left"
        )

        telegram_ok = self.telegram.send_low_stock_alert(
            product_name, platform, stock_qty
        )
        email_ok = self.email.send_low_stock_alert(
            product_name, platform, stock_qty
        )

        return self._record_result(
            "low_stock_alert",
            telegram_ok,
            email_ok
        )

    def system_error(self, title: str, detail: str) -> bool:
        """
        Called when the system encounters a critical error.
        Only sends to Telegram (faster, no email needed for errors).

        USAGE (from scheduler when polling fails):
            notifier.system_error(
                "Gmail polling failed",
                "3 consecutive failures. Last error: ConnectionError"
            )
        """
        logger.error(f"System alert: {title} — {detail}")
        return self.telegram.send_system_alert(title, detail)

    def polling_summary(
        self,
        orders_found: int,
        messages_found: int,
        errors: int
    ) -> None:
        """
        Sends a daily summary (optional — only if activity exists).
        Not sent every poll — only once a day if anything happened.

        WHY OPTIONAL SUMMARY?
        Sending a "nothing happened" message every 5 minutes
        would be noise. This only fires if there was activity.
        """
        if orders_found == 0 and messages_found == 0:
            return  # Nothing to report

        message = (
            f"📊 <b>Daily Activity Summary</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🛒 Orders today: {orders_found}\n"
            f"💬 Messages today: {messages_found}\n"
        )

        if errors > 0:
            message += f"⚠️ Errors: {errors}\n"

        message += f"━━━━━━━━━━━━━━━━━━"

        self.telegram.send(message)

    def _record_result(
        self,
        alert_type: str,
        telegram_ok: bool,
        email_ok: bool
    ) -> bool:
        """
        Records notification statistics and returns success status.

        WHY TRACK STATISTICS?
        These numbers are exposed via the /metrics endpoint
        and shown in Grafana. You can see notification delivery
        rate over time — if it drops, something is wrong.

        INTERVIEW POINT:
        "I tracked notification success rates as metrics and
         exposed them to Prometheus. If the delivery rate drops
         below 90%, Grafana fires an alert. This gives us
         observability into the notification pipeline itself,
         not just the business events."
        """
        self.stats["total_sent"] += 1

        if telegram_ok:
            self.stats["telegram_sent"] += 1
        if email_ok:
            self.stats["email_sent"] += 1

        success = telegram_ok or email_ok
        # At least one channel worked = success

        if not success:
            self.stats["failures"] += 1
            logger.error(
                f"All notification channels failed for {alert_type}. "
                f"Stats: {self.stats}"
            )
        else:
            logger.info(
                f"{alert_type} sent — "
                f"Telegram: {'✓' if telegram_ok else '✗'} "
                f"Email: {'✓' if email_ok else '✗'}"
            )

        return success

    def get_stats(self) -> Dict:
        """Returns current notification statistics for /metrics endpoint."""
        return {
            **self.stats,
            "success_rate": (
                round(
                    (self.stats["total_sent"] - self.stats["failures"])
                    / max(self.stats["total_sent"], 1)
                    * 100,
                    1
                )
            )
        }


# Create a single shared instance
# This is the Singleton pattern — one Notifier for the whole app
# Imported everywhere as: from app.notifications.notifier import notifier
notifier = Notifier()