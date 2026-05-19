# backend/app/notifications/email_alert.py
#
# PURPOSE: Sends email alerts via Gmail SMTP
#
# This is the same Gmail SMTP logic we tested earlier,
# now properly structured as a class with specific
# alert methods for each event type.
#
# WHY EMAIL IN ADDITION TO TELEGRAM?
# Telegram is fast but emails are searchable and archivable.
# You can search "order" in Gmail and see every order email
# we sent — useful for quick reference. Also useful if you
# ever check email but not Telegram.

import sys
import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

sys.path.append(
    os.path.join(os.path.dirname(__file__), '..', '..', '..')
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailAlerter:
    """
    Sends HTML email alerts via Gmail SMTP.

    WHY HTML EMAILS?
    Plain text alerts are readable but ugly.
    HTML lets us use tables, colours, and formatting —
    making alerts scannable at a glance on mobile.
    We always include a plain text fallback for email
    clients that don't render HTML.
    """

    def __init__(self):
        self.gmail_address  = settings.GMAIL_ADDRESS
        self.app_password   = settings.GMAIL_APP_PASSWORD
        self.smtp_server    = "smtp.gmail.com"
        self.smtp_port      = 587

        if not self.gmail_address or not self.app_password:
            logger.warning(
                "Gmail credentials missing — email alerts disabled"
            )
            self.enabled = False
        else:
            self.enabled = True
            logger.info("Email alerter initialised")

    def send(
        self,
        subject: str,
        html_body: str,
        plain_body: str = ""
    ) -> bool:
        """
        Sends an HTML email to yourself.

        HOW SMTP WORKS (for interviews):
        1. Create TCP connection to smtp.gmail.com:587
        2. ehlo() — "hello, I am a mail client"
        3. starttls() — upgrade connection to encrypted TLS
        4. ehlo() again — re-identify over encrypted connection
        5. login() — authenticate with email + app password
        6. sendmail() — send the email
        7. Connection auto-closes via 'with' block

        WHY PORT 587 NOT 465?
        Port 465 = SMTPS (SSL from the start, older standard)
        Port 587 = SMTP + STARTTLS (starts plain, upgrades to TLS)
        587 with STARTTLS is the current recommended standard.
        Both are encrypted — 587 is just more widely supported.
        """
        if not self.enabled:
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = self.gmail_address
            msg["To"]      = self.gmail_address
            # Sending to yourself — this is your own business alert system

            # Plain text fallback
            # Some email clients or email filter systems show plain text
            plain_fallback = plain_body or self._strip_html(html_body)
            msg.attach(MIMEText(plain_fallback, "plain"))
            msg.attach(MIMEText(html_body, "html"))
            # Order matters: plain first, HTML second
            # Email client shows the LAST part it can render
            # So HTML-capable clients show HTML, others show plain

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(self.gmail_address, self.app_password)
                server.sendmail(
                    self.gmail_address,
                    self.gmail_address,
                    msg.as_string()
                )

            logger.info(f"Email sent: {subject}")
            return True

        except smtplib.SMTPAuthenticationError:
            # Specific error for wrong credentials
            # Log clearly so the developer knows exactly what's wrong
            logger.error(
                "Gmail SMTP authentication failed. "
                "Check GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env"
            )
            return False

        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            return False

        except Exception as e:
            logger.error(f"Email alert unexpected error: {e}")
            return False

    def send_order_alert(self, order_data: dict) -> bool:
        """Sends a formatted order notification email."""
        platform = order_data.get("platform", "unknown").upper()
        product  = order_data.get("product_name", "Unknown Product")
        price    = order_data.get("sale_price", 0)
        fee      = order_data.get("platform_fee", 0)
        net      = order_data.get("net_revenue", 0)
        buyer    = order_data.get("buyer_name", "Unknown")
        city     = order_data.get("shipping_city", "")
        country  = order_data.get("shipping_country", "")
        order_id = order_data.get("order_id", "N/A")

        subject = f"🛒 New {platform} Order — {product[:40]}"

        html = f"""
        <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">

        <div style="background: #1E3A5F; padding: 20px; border-radius: 8px 8px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 22px;">
                🛒 New {platform} Order!
            </h1>
            <p style="color: #AED6F1; margin: 5px 0 0 0; font-size: 14px;">
                {datetime.now().strftime('%A, %d %B %Y at %H:%M')}
            </p>
        </div>

        <div style="background: #f8f9fa; padding: 20px; border-radius: 0 0 8px 8px;">

            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #dee2e6;
                                font-weight: bold; color: #555; width: 35%;">
                        📦 Product
                    </td>
                    <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">
                        {product}
                    </td>
                </tr>
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #dee2e6;
                                font-weight: bold; color: #555;">
                        💰 Sale Price
                    </td>
                    <td style="padding: 10px; border-bottom: 1px solid #dee2e6;
                                font-size: 18px; font-weight: bold; color: #1E3A5F;">
                        ${price:.2f}
                    </td>
                </tr>
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #dee2e6;
                                font-weight: bold; color: #555;">
                        💵 Net Revenue
                    </td>
                    <td style="padding: 10px; border-bottom: 1px solid #dee2e6;
                                color: #27ae60; font-weight: bold;">
                        ${net:.2f}
                        <span style="color: #888; font-weight: normal;
                                     font-size: 12px;">
                            (after ${fee:.2f} {platform} fee)
                        </span>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #dee2e6;
                                font-weight: bold; color: #555;">
                        👤 Buyer
                    </td>
                    <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">
                        {buyer}
                    </td>
                </tr>
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #dee2e6;
                                font-weight: bold; color: #555;">
                        📍 Ships To
                    </td>
                    <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">
                        {city} {country}
                    </td>
                </tr>
                <tr>
                    <td style="padding: 10px; font-weight: bold; color: #555;">
                        🔖 Order ID
                    </td>
                    <td style="padding: 10px; font-family: monospace;">
                        {order_id}
                    </td>
                </tr>
            </table>

            <p style="margin-top: 20px; padding: 12px; background: #e8f4f8;
                       border-radius: 6px; font-size: 13px; color: #555;">
                This order has been automatically saved to your
                RiMitLayers database.
            </p>
        </div>

        </body></html>
        """
        return self.send(subject, html)

    def send_message_alert(self, message_data: dict) -> bool:
        """Sends a formatted buyer message notification email."""
        platform = message_data.get("platform", "unknown").upper()
        buyer    = message_data.get("buyer_name", "Unknown")
        preview  = message_data.get("preview", "No preview available")
        subject  = f"💬 New {platform} Message from {buyer}"

        html = f"""
        <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">

        <div style="background: #1E3A5F; padding: 20px; border-radius: 8px 8px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 22px;">
                💬 New {platform} Message
            </h1>
        </div>

        <div style="background: #f8f9fa; padding: 20px; border-radius: 0 0 8px 8px;">
            <p><strong>From:</strong> {buyer}</p>
            <div style="background: white; padding: 15px; border-left: 4px solid #1E3A5F;
                         border-radius: 4px; margin: 15px 0;">
                <p style="margin: 0; color: #333;">{preview}</p>
            </div>
            <p style="color: #888; font-size: 13px;">
                Reply directly in your {platform} inbox.
                An AI draft reply is available in your dashboard.
            </p>
        </div>

        </body></html>
        """
        return self.send(subject, html)

    def send_low_stock_alert(
        self,
        product_name: str,
        platform: str,
        stock_qty: int
    ) -> bool:
        """Sends a low stock warning email."""
        subject = f"⚠️ Low Stock: {product_name[:50]}"
        html = f"""
        <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #e74c3c; padding: 20px; border-radius: 8px 8px 0 0;">
            <h1 style="color: white; margin: 0;">⚠️ Low Stock Alert</h1>
        </div>
        <div style="background: #fdf2f2; padding: 20px; border-radius: 0 0 8px 8px;">
            <p><strong>Product:</strong> {product_name}</p>
            <p><strong>Platform:</strong> {platform.upper()}</p>
            <p><strong>Stock remaining:</strong>
                <span style="color: #e74c3c; font-size: 20px; font-weight: bold;">
                    {stock_qty}
                </span>
            </p>
            <p style="color: #888;">Please restock soon to avoid missing sales.</p>
        </div>
        </body></html>
        """
        return self.send(subject, html)

    def _strip_html(self, html: str) -> str:
        """
        Removes HTML tags to create plain text fallback.
        Simple implementation using string replacement.
        For production we'd use BeautifulSoup but this
        avoids an extra dependency for simple cases.
        """
        import re
        # Remove HTML tags
        plain = re.sub(r'<[^>]+>', ' ', html)
        # Collapse multiple spaces/newlines
        plain = re.sub(r'\s+', ' ', plain).strip()
        return plain