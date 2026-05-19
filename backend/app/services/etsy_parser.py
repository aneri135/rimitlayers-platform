# backend/app/services/etsy_parser.py
#
# PURPOSE: Extract structured data from Etsy notification emails
#
# ANALOGY: Think of this as reading a specific form.
# Etsy's order emails always have the same structure.
# This file knows exactly where each piece of data lives
# and how to extract it reliably.
#
# WHY REGEX FOR PARSING?
# Etsy emails are HTML converted to plain text. They don't have
# a structured format like JSON or XML. Regex (regular expressions)
# lets us find patterns in unstructured text.
#
# REGEX EXPLAINED (for interviews):
# r"Order #(\d+)" means:
# - r"..." = raw string (backslashes not treated as escape sequences)
# - "Order #" = match these literal characters
# - (\d+) = capture group — match one or more digits
# - The captured group is what we extract

import re
import logging
import hashlib
from datetime import datetime
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class EtsyParser:
    """
    Extracts structured data from Etsy order and message emails.
    Returns dictionaries ready to be saved as Sale or Message objects.
    """

    # Etsy fee structure (as of 2026)
    # These are applied automatically when calculating net_revenue
    TRANSACTION_FEE_RATE  = 0.065   # 6.5% of sale price
    PAYMENT_PROCESSING_RATE = 0.03  # 3% of sale price
    PAYMENT_PROCESSING_FLAT = 0.25  # + $0.25 per transaction

    def parse_order_email(
        self,
        email: Dict
    ) -> Optional[Dict]:
        """
        Parses an Etsy sale notification email.

        INPUT: email dict from GmailService
        OUTPUT: dict ready to create a Sale database record
                or None if parsing fails

        WHY RETURN NONE ON FAILURE?
        If we can't parse an email reliably, it's better to
        skip it and log a warning than to save incomplete/wrong
        data to your database. Bad data is worse than no data
        for tax purposes.
        """
        body    = email.get("body", "")
        subject = email.get("subject", "")
        date    = email.get("date", datetime.now())

        try:
            # Extract each field — each method returns None if not found
            order_id     = self._extract_order_id(body, subject)
            product_name = self._extract_product_name(body)
            sale_price   = self._extract_price(body)
            buyer_name   = self._extract_buyer_name(body)
            address      = self._extract_address(body)
            quantity     = self._extract_quantity(body)

            # order_id and sale_price are the minimum required fields
            # Without these we can't create a meaningful record
            if not order_id:
                logger.warning("Could not extract order ID from Etsy email")
                return None
            if not sale_price:
                logger.warning(f"Could not extract price from Etsy order {order_id}")
                return None

            # Calculate fees automatically
            # This is done here so fee data is always consistent
            fees = self._calculate_fees(sale_price)

            return {
                "order_id":           order_id,
                "platform":           "etsy",
                "order_date":         date,
                "product_name":       product_name or "Unknown Product",
                "category":           self._guess_category(product_name),
                "quantity":           quantity or 1,
                "sale_price":         sale_price,
                "platform_fee":       fees["total_fee"],
                "shipping_collected": self._extract_shipping(body) or 0.0,
                "net_revenue":        sale_price - fees["total_fee"],
                "buyer_name":         buyer_name or "Unknown Buyer",
                "buyer_email":        None,
                "shipping_address":   address.get("full", ""),
                "shipping_city":      address.get("city", ""),
                "shipping_state":     address.get("state", ""),
                "shipping_country":   address.get("country", ""),
                "shipping_zip":       address.get("zip", ""),
                "status":             "completed",
                "source":             "email_parser",
                "notes":              f"Parsed from email: {subject[:100]}",
            }

        except Exception as e:
            logger.error(f"Error parsing Etsy order email: {e}", exc_info=True)
            # exc_info=True includes the full stack trace in logs
            return None

    def parse_message_email(self, email: Dict) -> Optional[Dict]:
        """
        Parses an Etsy buyer message notification email.
        """
        body    = email.get("body", "")
        subject = email.get("subject", "")
        date    = email.get("date", datetime.now())

        try:
            buyer_name = self._extract_buyer_name_from_message(body, subject)
            preview    = self._extract_message_preview(body)

            # Generate a unique ID for this message
            # hashlib creates a hash of the email content
            # This gives us a consistent ID even if Etsy doesn't provide one
            message_id = self._generate_message_id(
                buyer_name or "",
                preview or "",
                str(date)
            )

            return {
                "message_id":  message_id,
                "platform":    "etsy",
                "buyer_name":  buyer_name or "Unknown",
                "buyer_email": None,
                "subject":     subject,
                "preview":     (preview or "")[:200],
                # [:200] = first 200 characters only — preview not full body
                "full_body":   body,
                "received_at": date,
                "is_read":     False,
                "is_replied":  False,
            }

        except Exception as e:
            logger.error(f"Error parsing Etsy message email: {e}")
            return None

    # ============================================================
    # PRIVATE EXTRACTION METHODS
    # Each method extracts one specific field.
    # Returns None if the field can't be found — never crashes.
    # ============================================================

    def _extract_order_id(
        self,
        body: str,
        subject: str
    ) -> Optional[str]:
        """
        Extracts Etsy order number.

        The order number appears in subject inside [..., Order #XXXXXXXXXX]
        and also in the email body.
        """
        # Try subject first — most reliable
        # Matches: Order #4067696529 anywhere in subject
        patterns = [
            r"Order\s*#\s*(\d{8,12})",      # "Order #4067696529"
            r"#(\d{8,12})\]",               # "#4067696529]" at end of subject
            r"order number is:\s*(\d{8,12})", # "Your order number is: 4067696529"
            r"order[:\s#]*(\d{8,12})",       # fallback
        ]

        for text in [subject, body]:
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return f"etsy_{match.group(1)}"

        # Hash-based fallback
        return f"etsy_email_{hashlib.md5(body[:100].encode()).hexdigest()[:8]}"

    def _extract_price(self, body: str) -> Optional[float]:
        """
        REAL ETSY EMAIL PRICE FORMAT (from live testing):
        "Price: $21.99"
        "Item total: $21.99"
        "Subtotal: $18.69"  (after discount — use original price not subtotal)
        """
        patterns = [
            r"Price:\s*\$\s*([\d,]+\.?\d*)",        # "Price: $21.99"
            r"Item total:\s*\$\s*([\d,]+\.?\d*)",    # "Item total: $21.99"
            r"price[:\s]*\$\s*([\d,]+\.?\d*)",       # generic price
            r"\$\s*([\d,]+\.?\d*)",                  # any dollar amount
        ]
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    continue
        return None

    def _extract_product_name(self, body: str) -> Optional[str]:
        """
        REAL ETSY EMAIL PRODUCT FORMAT:
        Product name appears as a clickable link in the email.
        Usually the longest descriptive text near the top.

        "Modern Spiral 3D Printed Decorative Vase - Sculptural Home Decor..."
        """
        patterns = [
            # After "Quantity: N" line, product name is usually nearby
            r"([A-Z][a-zA-Z0-9\s\-\|,]+(?:3D|Printed|Lithophane|Lantern|Vase)[a-zA-Z0-9\s\-\|,]+?)(?:\n|Shop:)",
            # Common product name patterns for RiMitLayers products
            r"((?:3D Printed|Custom|Modern|Spiral|Halloween|Christmas|Santa)[a-zA-Z0-9\s\-\|,\.]+?)(?:\n|Shop:|Transaction)",
            # Generic: any long capitalised phrase
            r"([A-Z][a-zA-Z0-9\s\-\|]{20,100})(?:\n|Shop:)",
        ]
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                if len(name) > 10:
                    return name[:300]
        return None

    def _extract_buyer_name(self, body: str) -> Optional[str]:
        """
        The buyer name is the FIRST line after "Shipping address"
        """
        patterns = [
            # Match name after "Shipping address" label — real Etsy format
            r"Shipping address\s*\n\s*([A-Z][a-zA-Z\s\-'\.]+?)(?:\n|$)",
            # Match name after "Ship to:" label
            r"[Ss]hip\s+to[:\s]*\n?\s*([A-Z][a-zA-Z\s\-'\.]+?)(?:\n|,|\d)",
            # Match name in "sold to" context
            r"[Ss]old\s+to[:\s]*\n?\s*([A-Z][a-zA-Z\s\-'\.]+?)(?:\n|,|\d)",
        ]
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Validate: name should be 2+ words, no digits
                words = name.split()
                if len(words) >= 2 and not any(c.isdigit() for c in name):
                    return name[:100]
        return None

    def _extract_buyer_name_from_message(
        self,
        body: str,
        subject: str
    ) -> Optional[str]:
        """Extracts buyer name from message notification email."""
        patterns = [
            r"([A-Z][a-z]+ [A-Z][a-z]+)\s+sent you a message",
            r"message from\s+([A-Z][a-z]+ [A-Z][a-z]+)",
            r"^([A-Z][a-z]+ [A-Z][a-z]+)\s+has sent",
        ]
        for text in [subject, body]:
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1).strip()
        return None

    def _extract_address(self, body: str) -> Dict:
        """

        We extract each component separately.
        """
        address = {
            "full": "", "city": "", "state": "",
            "country": "", "zip": ""
        }

        # Find the shipping address block
        # Etsy puts it after "Shipping address" header
        addr_patterns = [
            r"Shipping address\s*\n(.+?)(?:\n\n|\Z)",
            r"Ship\s+to[:\s]*\n(.+?)(?:\n\n|\Z)",
        ]

        addr_block = ""
        for pattern in addr_patterns:
            match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
            if match:
                addr_block = match.group(1).strip()
                break

        if addr_block:
            address["full"] = addr_block[:500]
            lines = [l.strip() for l in addr_block.split("\n") if l.strip()]

            # Last line is usually country
            if lines:
                last = lines[-1]
                if any(country in last.upper() for country in [
                    "UNITED STATES", "CANADA", "UK", "UNITED KINGDOM",
                    "AUSTRALIA", "INDIA", "GERMANY", "FRANCE"
                ]):
                    address["country"] = last
                elif last.upper() == "UNITED STATES" or re.match(r'^[A-Z\s]+$', last):
                    address["country"] = last

            # Extract US zip code (5 digit or ZIP+4)
            zip_match = re.search(r"\b(\d{5}(?:-\d{4})?)\b", addr_block)
            if zip_match:
                address["zip"] = zip_match.group(1)

            # Extract state and city from "CITY, ST ZIPCODE" format
            # e.g. "ELIZABETH, CO 80107-7869"
            city_state = re.search(
                r"([A-Z][A-Z\s]+),\s+([A-Z]{2})\s+\d{5}",
                addr_block,
                re.IGNORECASE
            )
            if city_state:
                address["city"]  = city_state.group(1).strip().title()
                address["state"] = city_state.group(2).strip().upper()

        # If no block found, try extracting components individually
        if not address["zip"]:
            zip_match = re.search(r"\b(\d{5}(?:-\d{4})?)\b", body)
            if zip_match:
                address["zip"] = zip_match.group(1)

        return address


    def _extract_quantity(self, body: str) -> Optional[int]:
        """Extracts quantity ordered."""
        match = re.search(
            r"qty[:\s]*(\d+)|quantity[:\s]*(\d+)",
            body,
            re.IGNORECASE
        )
        if match:
            # match.group(1) or match.group(2) — whichever captured
            qty = match.group(1) or match.group(2)
            return int(qty)
        return 1  # Default to 1 if not found

    def _extract_shipping(self, body: str) -> Optional[float]:
        """Extracts shipping amount collected from buyer."""
        match = re.search(
            r"shipping[:\s]*\$\s*([\d.]+)",
            body,
            re.IGNORECASE
        )
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return 0.0
        return 0.0

    def _extract_message_preview(self, body: str) -> Optional[str]:
        """Extracts the buyer's message text preview."""
        patterns = [
            r"message:\s*(.+?)(?:\n\n|reply|view|etsy\.com)",
            r"wrote:\s*(.+?)(?:\n\n|reply|view)",
            r"says:\s*(.+?)(?:\n\n|reply|view)",
        ]
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
            if match:
                preview = match.group(1).strip()
                if len(preview) > 10:
                    return preview[:500]
        # Fallback — return first 300 chars of body
        return body[:300] if body else None

    def _calculate_fees(self, sale_price: float) -> Dict:
        """
        Calculates Etsy fees for a given sale price.

        ETSY FEE STRUCTURE (2026):
        - Transaction fee: 6.5% of sale price
        - Payment processing: 3% + $0.25 per transaction
        - Listing fee: $0.20 per item (tracked separately in fees table)

        WHY CALCULATE HERE?
        Etsy emails don't always show the fee breakdown clearly.
        By calculating from the known fee structure, we get
        consistent accurate numbers for tax reporting.
        """
        transaction_fee  = round(sale_price * self.TRANSACTION_FEE_RATE, 2)
        processing_fee   = round(
            sale_price * self.PAYMENT_PROCESSING_RATE + self.PAYMENT_PROCESSING_FLAT,
            2
        )
        total_fee = round(transaction_fee + processing_fee, 2)

        return {
            "transaction_fee":  transaction_fee,
            "processing_fee":   processing_fee,
            "total_fee":        total_fee,
        }

    def _guess_category(self, product_name: Optional[str]) -> str:
        """
        Guesses product category from product name.
        Helps organise dashboard by category.
        """
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
        """
        Generates a consistent unique ID from message content.
        Used when Etsy doesn't provide an explicit message ID.

        MD5 hash of combined content gives us a consistent
        16-character ID that's the same every time for the
        same email — preventing duplicates.
        """
        combined = "|".join(parts)
        return f"etsy_msg_{hashlib.md5(combined.encode()).hexdigest()[:12]}"