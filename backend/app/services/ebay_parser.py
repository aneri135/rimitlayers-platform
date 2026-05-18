# backend/app/services/ebay_parser.py
#
# PURPOSE: Extract structured data from eBay notification emails
#
# WHY A SEPARATE FILE FROM etsy_parser.py?
# eBay and Etsy emails have completely different formats.
# eBay says "You sold: Skull Tealight Lantern"
# Etsy says "You made a sale!"
# eBay fees: 13.25% final value fee
# Etsy fees: 6.5% transaction + 3% processing
#
# Keeping them separate means:
# - Changing eBay's fee structure only touches this file
# - Adding eBay-specific fields doesn't affect Etsy parser
# - Testing each independently is straightforward


import re
import logging
import hashlib
from datetime import datetime
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class EbayParser:
    """Extracts structured data from eBay order and message emails."""

    # eBay fee structure (2026 — Standard seller)
    FINAL_VALUE_FEE_RATE     = 0.1325  # 13.25% of total sale amount
    INTERNATIONAL_FEE_RATE   = 0.0165  # 1.65% on international sales

    def parse_order_email(self, email: Dict) -> Optional[Dict]:
        """Parses an eBay sold notification email."""
        body    = email.get("body", "")
        subject = email.get("subject", "")
        date    = email.get("date", datetime.now())

        try:
            order_id     = self._extract_order_id(body, subject)
            product_name = self._extract_product_name(body, subject)
            sale_price   = self._extract_price(body)
            buyer_name   = self._extract_buyer_name(body)
            address      = self._extract_address(body)
            quantity     = self._extract_quantity(body)

            if not order_id:
                logger.warning("Could not extract order ID from eBay email")
                return None
            if not sale_price:
                logger.warning(f"Could not extract price from eBay order {order_id}")
                return None

            fees = self._calculate_fees(sale_price)
            is_international = self._is_international(address)
            if is_international:
                # Add international fee for non-US shipments
                intl_fee = round(sale_price * self.INTERNATIONAL_FEE_RATE, 2)
                fees["total_fee"] += intl_fee

            return {
                "order_id":           order_id,
                "platform":           "ebay",
                "order_date":         date,
                "product_name":       product_name or "Unknown Product",
                "category":           self._guess_category(product_name),
                "quantity":           quantity or 1,
                "sale_price":         sale_price,
                "platform_fee":       fees["total_fee"],
                "shipping_collected": self._extract_shipping(body) or 0.0,
                "net_revenue":        round(sale_price - fees["total_fee"], 2),
                "buyer_name":         buyer_name or "Unknown Buyer",
                "buyer_email":        None,
                "shipping_address":   address.get("full", ""),
                "shipping_city":      address.get("city", ""),
                "shipping_state":     address.get("state", ""),
                "shipping_country":   address.get("country", ""),
                "shipping_zip":       address.get("zip", ""),
                "status":             "completed",
                "source":             "email_parser",
                "notes":              f"Parsed from eBay email: {subject[:100]}",
            }

        except Exception as e:
            logger.error(f"Error parsing eBay order email: {e}", exc_info=True)
            return None

    def parse_message_email(self, email: Dict) -> Optional[Dict]:
        """Parses an eBay buyer message notification email."""
        body    = email.get("body", "")
        subject = email.get("subject", "")
        date    = email.get("date", datetime.now())

        try:
            buyer_name = self._extract_buyer_name_from_message(body, subject)
            preview    = self._extract_message_preview(body)
            message_id = self._generate_message_id(
                buyer_name or "", preview or "", str(date)
            )

            return {
                "message_id":  message_id,
                "platform":    "ebay",
                "buyer_name":  buyer_name or "Unknown",
                "buyer_email": None,
                "subject":     subject,
                "preview":     (preview or "")[:200],
                "full_body":   body,
                "received_at": date,
                "is_read":     False,
                "is_replied":  False,
            }
        except Exception as e:
            logger.error(f"Error parsing eBay message email: {e}")
            return None

    def _extract_order_id(self, body: str, subject: str) -> Optional[str]:
        """eBay order IDs are typically 12-digit numbers."""
        patterns = [
            r"order\s+(?:id|number|#)[:\s]*(\d{10,18})",
            r"transaction\s+id[:\s]*(\d{10,18})",
            r"#(\d{10,18})",
        ]
        for text in [body, subject]:
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return f"ebay_{match.group(1)}"
        # Fallback hash-based ID
        return f"ebay_email_{hashlib.md5(body[:100].encode()).hexdigest()[:8]}"

    def _extract_product_name(
        self,
        body: str,
        subject: str
    ) -> Optional[str]:
        """eBay emails often have item name in subject: 'You sold: [Item]'"""
        # Try subject first
        subject_match = re.search(
            r"sold:\s*(.+?)(?:\s*[-|]|$)",
            subject,
            re.IGNORECASE
        )
        if subject_match:
            return subject_match.group(1).strip()[:200]

        # Try body
        body_patterns = [
            r"item:\s*(.+?)(?:\n|price|qty)",
            r"listing:\s*(.+?)(?:\n|$)",
        ]
        for pattern in body_patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                return match.group(1).strip()[:200]
        return None

    def _extract_price(self, body: str) -> Optional[float]:
        """Extracts sale price from eBay email."""
        patterns = [
            r"sale price[:\s]*\$\s*([\d,]+\.?\d*)",
            r"sold for[:\s]*\$\s*([\d,]+\.?\d*)",
            r"total[:\s]*\$\s*([\d,]+\.?\d*)",
            r"\$\s*([\d,]+\.?\d*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    continue
        return None

    def _extract_buyer_name(self, body: str) -> Optional[str]:
        """Extracts buyer username or name from eBay email."""
        patterns = [
            r"buyer[:\s]*([A-Za-z0-9_\-]+)",
            r"sold to[:\s]*([A-Za-z0-9_\-]+)",
            r"ship to[:\s]*([A-Z][a-z]+ [A-Z][a-z]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_buyer_name_from_message(
        self,
        body: str,
        subject: str
    ) -> Optional[str]:
        patterns = [
            r"([A-Za-z0-9_]+)\s+sent you a message",
            r"question from\s+([A-Za-z0-9_]+)",
            r"message from\s+([A-Za-z0-9_\s]+?)(?:\n|about)",
        ]
        for text in [subject, body]:
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1).strip()
        return None

    def _extract_address(self, body: str) -> Dict:
        """Extracts shipping address from eBay email."""
        address = {
            "full": "", "city": "", "state": "",
            "country": "", "zip": ""
        }
        addr_match = re.search(
            r"ship\s+to[:\s]*(.+?)(?:order|item|from ebay|\Z)",
            body,
            re.IGNORECASE | re.DOTALL
        )
        if addr_match:
            full_addr = addr_match.group(1).strip()
            address["full"] = full_addr[:500]
            zip_match = re.search(r"\b(\d{5}(?:-\d{4})?)\b", full_addr)
            if zip_match:
                address["zip"] = zip_match.group(1)
            state_match = re.search(r"\b([A-Z]{2})\b\s+\d{5}", full_addr)
            if state_match:
                address["state"] = state_match.group(1)
            # Check for non-US country
            country_match = re.search(
                r"\b(UK|United Kingdom|Canada|Australia|India|Germany)\b",
                full_addr, re.IGNORECASE
            )
            if country_match:
                address["country"] = country_match.group(1)
            else:
                address["country"] = "US"
        return address

    def _extract_quantity(self, body: str) -> int:
        match = re.search(
            r"qty[:\s]*(\d+)|quantity[:\s]*(\d+)",
            body, re.IGNORECASE
        )
        if match:
            qty = match.group(1) or match.group(2)
            return int(qty)
        return 1

    def _extract_shipping(self, body: str) -> float:
        match = re.search(
            r"shipping[:\s]*\$\s*([\d.]+)",
            body, re.IGNORECASE
        )
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return 0.0
        return 0.0

    def _extract_message_preview(self, body: str) -> Optional[str]:
        patterns = [
            r"message:\s*(.+?)(?:\n\n|reply|view|ebay\.com)",
            r"wrote:\s*(.+?)(?:\n\n|reply)",
            r"asks:\s*(.+?)(?:\n\n|reply)",
        ]
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
            if match:
                preview = match.group(1).strip()
                if len(preview) > 10:
                    return preview[:500]
        return body[:300] if body else None

    def _calculate_fees(self, sale_price: float) -> Dict:
        """
        Calculates eBay fees.
        eBay's final value fee covers both their cut AND payment processing.
        Different from Etsy which charges them separately.
        """
        final_value_fee = round(sale_price * self.FINAL_VALUE_FEE_RATE, 2)
        return {
            "final_value_fee": final_value_fee,
            "total_fee":       final_value_fee,
        }

    def _is_international(self, address: Dict) -> bool:
        """Returns True if shipping outside the US."""
        country = address.get("country", "US").upper()
        return country not in ["US", "USA", "UNITED STATES", ""]

    def _guess_category(self, product_name: Optional[str]) -> str:
        if not product_name:
            return "Other"
        name = product_name.lower()
        if any(w in name for w in ["lithophane", "litho", "photo"]):
            return "Lithophanes"
        elif any(w in name for w in ["lantern", "light", "led"]):
            return "Lanterns"
        elif any(w in name for w in ["vase", "planter", "pot"]):
            return "Vases"
        return "Other"

    def _generate_message_id(self, *parts: str) -> str:
        combined = "|".join(parts)
        return f"ebay_msg_{hashlib.md5(combined.encode()).hexdigest()[:12]}"