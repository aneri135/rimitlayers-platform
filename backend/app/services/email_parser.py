# backend/app/services/email_parser.py
#
# PURPOSE: Three-layer email classification and routing
#
# ANALOGY: This is the "sorter" at the post office.
# Letters come in (emails from GmailService), the sorter checks:
# 1. Is this from a legitimate sender?
# 2. What type of letter is it?
# 3. Does it contain what it claims to contain?
# Then routes to the right department (etsy_parser or ebay_parser)
#
# DESIGN PATTERN: Chain of Responsibility
# Each layer either passes the email forward or rejects it.
# If any layer rejects, processing stops immediately.
# No layer knows about the others — clean, testable, extendable.


import re
import logging
from datetime import datetime
from typing import Optional, Dict, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class EmailType(Enum):
    """
    WHY AN ENUM?
    Enums prevent typos. Without Enum:
        type = "orer"  # typo — silent bug
    With Enum:
        type = EmailType.ORER  # AttributeError — caught immediately

    """
    ORDER   = "order"
    MESSAGE = "message"
    IGNORE  = "ignore"
    UNKNOWN = "unknown"


class EmailClassification:
    """
    Result object returned after classifying an email.

    WHY A CLASS INSTEAD OF A DICTIONARY?
    With a dictionary: result["email_type"] — typo possible
    With a class: result.email_type — IDE autocomplete + type checking

    This is called a "Value Object" pattern — an object that
    holds the result of an operation with no behaviour of its own.
    """
    def __init__(
        self,
        email_type: EmailType,
        platform: str,
        confidence: float,
        reason: str
    ):
        self.email_type = email_type
        self.platform   = platform    # 'etsy', 'ebay', or 'unknown'
        self.confidence = confidence  # 0.0 to 1.0 — how sure we are
        self.reason     = reason      # Human-readable explanation

    def is_actionable(self) -> bool:
        """Returns True if this email should be processed (not ignored)"""
        return self.email_type in [EmailType.ORDER, EmailType.MESSAGE]

    def __repr__(self):
        return (
            f"<EmailClassification type={self.email_type.value} "
            f"platform={self.platform} confidence={self.confidence}>"
        )


class EmailParser:
    """
    Main email parser — orchestrates the three-layer validation.
    """

    # ============================================================
    # LAYER 1: TRUSTED SENDER DOMAINS
    # Only emails from these EXACT domains are processed.
    # Checked against the actual sending domain, not display name.
    #
    # WHY DOMAINS NOT FULL ADDRESSES?
    # Etsy uses multiple sending addresses:
    # - transaction@etsy.com
    # - auto-confirm@mail.etsy.com
    # - noreply@etsy.com
    # Checking domain covers all of them without hardcoding each one.
    # ============================================================
    TRUSTED_DOMAINS = {
        "etsy": [
            "@etsy.com",
            "@mail.etsy.com",
            "@e.etsy.com",
        ],
        "ebay": [
            "@ebay.com",
            "@reply.ebay.com",
            "@ebay.co.uk",
        ],
    }

    # ============================================================
    # LAYER 2: SUBJECT LINE PATTERNS
    # Regex patterns that identify order vs message emails.
    #
    # WHY REGEX?
    # Simple string matching: "You made a sale!" in subject
    # → breaks if Etsy adds punctuation or changes capitalisation
    # Regex: r"you made a sale" with re.IGNORECASE
    # → matches "You made a sale!", "you made a sale", "YOU MADE A SALE!"
    #
    # INTERVIEW POINT:
    # "I used case-insensitive regex for subject matching because
    #  email subjects can vary in capitalisation between email
    #  clients and Etsy platform versions."
    # ============================================================
    ORDER_SUBJECT_PATTERNS = {
        "etsy": [
            r"you made a sale",
            r"order #\d+",
            r"your etsy order receipt",
            r"order confirmation",
        ],
        "ebay": [
            r"you sold",
            r"order confirmation",
            r"sold:",
            r"item sold",
            r"congratulations.*sold",
        ],
    }

    MESSAGE_SUBJECT_PATTERNS = {
        "etsy": [
            r"sent you a message on etsy",
            r"new message from",
            r"you have a new message",
            r"message from.*etsy",
        ],
        "ebay": [
            r"sent you a message",
            r"new message about",
            r"question from",
            r"buyer message",
        ],
    }

    # ============================================================
    # LAYER 3: REQUIRED BODY CONTENT
    # Keywords that MUST exist in a real order/message email.
    # A phishing email won't contain real Etsy order numbers
    # and won't link to etsy.com/your/orders.
    # ============================================================
    ORDER_REQUIRED_CONTENT = {
        "etsy": [
            r"etsy\.com",           # must link to etsy.com
            r"\$[\d,]+\.\d{2}",    # must have a dollar amount
        ],
        "ebay": [
            r"ebay\.com",
            r"\$[\d,]+\.\d{2}",
        ],
    }

    MESSAGE_REQUIRED_CONTENT = {
        "etsy": [
            r"etsy\.com",
        ],
        "ebay": [
            r"ebay\.com",
        ],
    }

    def classify(self, email: Dict) -> EmailClassification:
        """
        Main classification method — runs all three layers.

        PARAMETERS:
        email: Dict from GmailService with keys:
            'from', 'subject', 'body', 'date', 'id'

        RETURNS:
        EmailClassification object with type, platform, confidence

        EARLY RETURN PATTERN:
        We return immediately when any layer fails.
        No need to run expensive Layer 3 if Layer 1 already rejected.
        This is called "fail fast" or "guard clauses".
        """
        sender  = email.get("from", "").lower()
        subject = email.get("subject", "").lower()
        body    = email.get("body", "").lower()

        # ---- LAYER 1: Sender domain check ----
        platform = self._check_sender_domain(sender)
        if not platform:
            logger.debug(f"Layer 1 REJECTED: untrusted sender: {sender[:50]}")
            return EmailClassification(
                EmailType.IGNORE,
                "unknown",
                0.0,
                f"Untrusted sender domain: {sender[:50]}"
            )
        logger.debug(f"Layer 1 PASSED: platform={platform} sender={sender[:50]}")

        # ---- LAYER 2: Subject classification ----
        email_type = self._classify_subject(subject, platform)
        if email_type == EmailType.IGNORE:
            logger.debug(f"Layer 2 REJECTED: subject not matched: {subject[:80]}")
            return EmailClassification(
                EmailType.IGNORE,
                platform,
                0.3,
                f"Subject not matched for {platform}: {subject[:80]}"
                # confidence=0.3 because domain was valid (not phishing)
                # just not an order/message email — could be newsletter
            )
        logger.debug(f"Layer 2 PASSED: type={email_type.value} subject={subject[:60]}")

        # ---- LAYER 3: Body content verification ----
        if not self._verify_body_content(body, email_type, platform):
            logger.warning(
                f"Layer 3 REJECTED: body missing required content. "
                f"POSSIBLE PHISHING. subject={subject[:60]}"
            )
            return EmailClassification(
                EmailType.UNKNOWN,
                platform,
                0.1,
                "Body missing required content — possible phishing attempt"
                # confidence=0.1 — very suspicious
                # Subject matched but body didn't — likely phishing
            )
        logger.info(
            f"All layers PASSED: {email_type.value} from {platform}"
        )

        return EmailClassification(
            email_type,
            platform,
            0.95,  # High confidence — passed all three layers
            f"Validated {email_type.value} from {platform}"
        )

    def _check_sender_domain(self, sender: str) -> Optional[str]:
        """
        LAYER 1: Checks if sender is from a trusted domain.

        Returns platform name ('etsy'/'ebay') or None if untrusted.

        HOW EMAIL SENDER WORKS:
        The "From" header looks like:
        "Etsy <transaction@etsy.com>"
        or just:
        "transaction@etsy.com"

        We check if any trusted domain appears ANYWHERE in the
        sender string. This catches both formats.

        ANTI-PHISHING LOGIC:
        "Etsy Support <support@totally-not-etsy.com>"
        → "etsy" appears in display name but domain is wrong
        → Our domain check fails → rejected

        We check for "@etsy.com" not just "etsy.com"
        "@" before the domain prevents matching "fake-etsy.com"
        """
        for platform, domains in self.TRUSTED_DOMAINS.items():
            for domain in domains:
                if domain in sender:
                    return platform
        return None

    def _classify_subject(
        self,
        subject: str,
        platform: str
    ) -> EmailType:
        """
        LAYER 2: Classifies email as ORDER, MESSAGE or IGNORE.

        Checks subject against all patterns for the detected platform.
        Returns the first match found.

        WHY re.search NOT re.match?
        re.match = only matches at START of string
        re.search = matches ANYWHERE in string

        Subject: "Congratulations! You made a sale on Etsy"
        re.match(r"you made a sale") → NO MATCH (string doesn't start with it)
        re.search(r"you made a sale") → MATCH ✓
        """
        # Check ORDER patterns
        order_patterns = self.ORDER_SUBJECT_PATTERNS.get(platform, [])
        for pattern in order_patterns:
            if re.search(pattern, subject, re.IGNORECASE):
                return EmailType.ORDER

        # Check MESSAGE patterns
        msg_patterns = self.MESSAGE_SUBJECT_PATTERNS.get(platform, [])
        for pattern in msg_patterns:
            if re.search(pattern, subject, re.IGNORECASE):
                return EmailType.MESSAGE

        # Nothing matched — not an order or message email
        return EmailType.IGNORE

    def _verify_body_content(
        self,
        body: str,
        email_type: EmailType,
        platform: str
    ) -> bool:
        """
        LAYER 3: Verifies required content exists in email body.

        WHY THIS MATTERS:
        A phishing email can fake the From address appearance
        and craft a subject that matches our patterns.
        But it cannot contain a real order number linked to
        your actual etsy.com/shop/orders page.

        ALL patterns must match — not just one.
        If even one required field is missing → suspicious → skip.

        all() built-in: returns True only if EVERY item is True
        any() built-in: returns True if AT LEAST ONE item is True
        We use all() — every required pattern must match.
        """
        if email_type == EmailType.ORDER:
            required = self.ORDER_REQUIRED_CONTENT.get(platform, [])
        elif email_type == EmailType.MESSAGE:
            required = self.MESSAGE_REQUIRED_CONTENT.get(platform, [])
        else:
            return True  # IGNORE type — no verification needed

        if not required:
            return True  # No requirements defined — pass through

        # Check ALL required patterns exist in body
        return all(
            re.search(pattern, body, re.IGNORECASE)
            for pattern in required
        )