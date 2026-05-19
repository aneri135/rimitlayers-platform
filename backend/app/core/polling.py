# backend/app/core/polling.py
#
# PURPOSE: The actual work that runs every 5 minutes
#
# ANALOGY: If the scheduler is the alarm clock, this is
# what you actually DO when the alarm goes off.
# Every 5 minutes: check Gmail → classify emails →
# save new orders/messages → send alerts → go back to sleep.
#
# WHY SEPARATE FROM scheduler.py?
# scheduler.py only defines WHEN things run.
# polling.py defines WHAT runs.
# This separation means you can:
# - Test the polling logic without touching the scheduler
# - Change timing without touching business logic
# - Add new jobs without modifying existing ones
#
# ERROR HANDLING PHILOSOPHY:
# This function MUST NEVER CRASH — it runs forever.
# Every operation is wrapped in try/except.
# If Gmail is down for one cycle → log it, move on.
# If one email fails to parse → log it, process the next one.
# The system is resilient by design.

import sys
import os
import logging
import pytz
from datetime import datetime, timezone
from typing import Optional
# System start time — only process emails NEWER than this
# Prevents old unread emails from triggering false alerts
# on first run


sys.path.append(
    os.path.join(os.path.dirname(__file__), '..', '..', '..')
)

from app.core.config import settings
from app.models.database import SessionLocal
from app.models.sale import Sale
from app.models.message import Message
from app.services.gmail_service import GmailService
from app.services.email_parser import EmailParser, EmailType
from app.services.etsy_parser import EtsyParser
from app.services.ebay_parser import EbayParser
from app.notifications.notifier import notifier

logger = logging.getLogger(__name__)

SYSTEM_START_TIME = datetime.now(timezone.utc)
logger.info(f"System start time set to: {SYSTEM_START_TIME}")

# Track consecutive failures for self-healing alerts
# Module-level variable persists between poll cycles
_consecutive_failures = 0
_FAILURE_ALERT_THRESHOLD = 3
# After 3 failures in a row → send system alert to Telegram

# Track daily stats for summary
_daily_stats = {
    "orders_found":   0,
    "messages_found": 0,
    "emails_skipped": 0,
    "errors":         0,
    "last_reset":     datetime.now(timezone.utc).date()
}


def run_poll_cycle() -> dict:
    """
    Main polling function — runs every 5 minutes.

    WHAT HAPPENS EACH CYCLE:
    1. Connect to Gmail (uses saved token — no browser)
    2. Search for unread emails from Etsy and eBay
    3. For each email:
       a. Run 3-layer classification
       b. If ORDER → parse → save to DB → send alert
       c. If MESSAGE → parse → save to DB → send alert
       d. If IGNORE → skip silently
       e. Mark email as read so we don't process it again
    4. Update stats
    5. Return summary of what happened

    RETURNS: dict with counts of what was found/processed

    WHY RETURN A DICT?
    The scheduler logs this return value.
    The /metrics API endpoint uses it.
    Makes it easy to see what happened each cycle.
    """
    global _consecutive_failures, _daily_stats

    cycle_start = datetime.now(timezone.utc)
    results = {
        "orders_found":   0,
        "messages_found": 0,
        "emails_skipped": 0,
        "errors":         0,
        "duration_ms":    0,
    }

    logger.info(
        f"Poll cycle starting at "
        f"{cycle_start.strftime('%H:%M:%S UTC')}"
    )

    try:
        # Step 1: Get Gmail service
        # GmailService handles token refresh automatically
        gmail   = GmailService()
        parser  = EmailParser()
        etsy_p  = EtsyParser()
        ebay_p  = EbayParser()

        # Step 2: Fetch unread emails from Etsy and eBay only
        # We pass sender domains so Gmail API filters server-side
        # This is more efficient than fetching ALL emails and filtering locally
        emails = gmail.get_unread_emails(
            from_addresses=[
                "etsy.com",
                "mail.etsy.com",
                "e.etsy.com",
                "ebay.com",
                "reply.ebay.com",
            ],
            max_results=50
            # Process max 50 emails per cycle
            # Safety limit — prevents overload if inbox is full
        )

        emails = [
            e for e in emails
            if e.get("date") and (
            # Handle both timezone-aware and naive datetimes
            (hasattr(e["date"], "tzinfo") and e["date"].tzinfo and
            e["date"] >= SYSTEM_START_TIME)
            or
            (hasattr(e["date"], "tzinfo") and not e["date"].tzinfo and
            e["date"] >= SYSTEM_START_TIME.replace(tzinfo=None))
        )
    ]

        logger.info(
    f"After date filter: {len(emails)} emails from last 5 min window"
)

        # Step 3: Process each email
        for email in emails:
            try:
                _process_single_email(
                    email, parser, etsy_p, ebay_p, gmail, results
                )
            except Exception as e:
                # ONE email failing never stops the others
                # This is the key resilience design decision
                results["errors"] += 1
                logger.error(
                    f"Error processing email {email.get('id', 'unknown')}: "
                    f"{e}",
                    exc_info=True
                )

        # Step 4: Update daily stats
        _update_daily_stats(results)

        # Step 5: Reset consecutive failure counter on success
        _consecutive_failures = 0

        # Step 6: Calculate duration
        duration = (
            datetime.now(timezone.utc) - cycle_start
        ).total_seconds() * 1000
        results["duration_ms"] = round(duration)

        logger.info(
            f"Poll cycle complete in {results['duration_ms']}ms — "
            f"Orders: {results['orders_found']} | "
            f"Messages: {results['messages_found']} | "
            f"Skipped: {results['emails_skipped']} | "
            f"Errors: {results['errors']}"
        )

        return results

    except Exception as e:
        # The ENTIRE cycle failed — something seriously wrong
        _consecutive_failures += 1
        results["errors"] += 1

        logger.error(
            f"Poll cycle failed (consecutive failure "
            f"{_consecutive_failures}): {e}",
            exc_info=True
        )

        # Send self-healing alert after threshold reached
        if _consecutive_failures >= _FAILURE_ALERT_THRESHOLD:
            notifier.system_error(
                "Polling failed repeatedly",
                f"{_consecutive_failures} consecutive failures. "
                f"Last error: {str(e)[:200]}"
            )
            # Reset counter after alerting so we don't spam
            _consecutive_failures = 0

        return results


def _process_single_email(
    email: dict,
    parser: EmailParser,
    etsy_p: EtsyParser,
    ebay_p: EbayParser,
    gmail: GmailService,
    results: dict
) -> None:
    """
    Processes one email through the full pipeline.

    Broken out as a separate function for two reasons:
    1. Keeps run_poll_cycle() readable and high-level
    2. The outer try/except in run_poll_cycle catches
       any error here without crashing other emails

    STEPS:
    classify → route to parser → save to DB → notify → mark read
    """
    email_id = email.get("id", "unknown")
    subject  = email.get("subject", "")[:60]

    logger.debug(f"Processing email: {subject}")

    # Step A: Classify the email (3-layer validation)
    classification = parser.classify(email)

    if not classification.is_actionable():
        # IGNORE — newsletter, promo, or phishing attempt
        results["emails_skipped"] += 1
        logger.debug(
            f"Skipped: {classification.reason[:80]}"
        )
        # Still mark as read so we don't see it next poll
        gmail.mark_as_read(email_id)
        return

    platform = classification.platform

    # Step B: Route to correct platform parser
    if classification.email_type == EmailType.ORDER:
        _handle_order_email(
            email, platform, etsy_p, ebay_p, results
        )

    elif classification.email_type == EmailType.MESSAGE:
        _handle_message_email(
            email, platform, etsy_p, ebay_p, results
        )

    # Step C: Mark as read AFTER successful processing
    # If we marked it read before processing and processing
    # crashed, we'd lose the email forever.
    # Mark AFTER = safe, idempotent retry if crash occurs
    gmail.mark_as_read(email_id)


def _handle_order_email(
    email: dict,
    platform: str,
    etsy_p: EtsyParser,
    ebay_p: EbayParser,
    results: dict
) -> None:
    """
    Handles a validated order email.
    Parses → saves to DB → sends notification.
    """
    # Parse the email using the correct platform parser
    if platform == "etsy":
        order_data = etsy_p.parse_order_email(email)
    elif platform == "ebay":
        order_data = ebay_p.parse_order_email(email)
    else:
        logger.warning(f"Unknown platform: {platform}")
        return

    if not order_data:
        logger.warning(
            f"Could not parse order from {platform} email — skipping"
        )
        return

    # Save to database
    saved = _save_order_to_db(order_data)

    if saved:
        results["orders_found"] += 1
        # Send Telegram + email alert
        notifier.order_received(order_data)
        logger.info(
            f"New order saved and alerted: "
            f"{platform} | {order_data.get('product_name')} | "
            f"${order_data.get('sale_price')}"
        )
    else:
        logger.info(
            f"Order {order_data.get('order_id')} already exists "
            f"in database — skipping (duplicate)"
        )
        # Not incrementing results["orders_found"] — not a new order


def _handle_message_email(
    email: dict,
    platform: str,
    etsy_p: EtsyParser,
    ebay_p: EbayParser,
    results: dict
) -> None:
    """
    Handles a validated buyer message email.
    Parses → saves to DB → sends notification.
    """
    if platform == "etsy":
        message_data = etsy_p.parse_message_email(email)
    elif platform == "ebay":
        message_data = ebay_p.parse_message_email(email)
    else:
        return

    if not message_data:
        return

    saved = _save_message_to_db(message_data)

    if saved:
        results["messages_found"] += 1
        notifier.message_received(message_data)
        logger.info(
            f"New message saved and alerted: "
            f"{platform} from {message_data.get('buyer_name')}"
        )
    else:
        logger.info(
            f"Message {message_data.get('message_id')} already "
            f"exists — skipping"
        )


def _save_order_to_db(order_data: dict) -> bool:
    """
    Saves an order to the database.

    RETURNS:
    True  = saved successfully (new record)
    False = order already exists (duplicate — don't alert again)

    HOW DUPLICATE DETECTION WORKS:
    The sales table has unique=True on order_id.
    If we try to insert the same order_id twice,
    the database raises an IntegrityError.
    We catch that and return False — not an error,
    just a "we already know about this order" signal.

    WHY DB-LEVEL CONSTRAINT NOT JUST CODE CHECK?
    Code check: check if exists → if not → insert
    This has a race condition — two threads could both
    check "does it exist?" get "no", and both try to insert.
    DB-level unique constraint makes it atomic — the database
    guarantees only one insert succeeds.

    INTERVIEW POINT:
    "I used database-level unique constraints for deduplication
     rather than application-level checks. Database constraints
     are atomic — they prevent race conditions that application
     code checks cannot. The unique index on order_id also makes
     duplicate lookups O(1) — instant regardless of table size."
    """
    db = SessionLocal()
    try:
        sale = Sale(
            order_id=           order_data["order_id"],
            platform=           order_data["platform"],
            order_date=         order_data.get("order_date", datetime.now()),
            product_name=       order_data.get("product_name", "Unknown"),
            category=           order_data.get("category", "Other"),
            quantity=           order_data.get("quantity", 1),
            sale_price=         order_data.get("sale_price", 0.0),
            platform_fee=       order_data.get("platform_fee", 0.0),
            shipping_collected= order_data.get("shipping_collected", 0.0),
            net_revenue=        order_data.get("net_revenue", 0.0),
            buyer_name=         order_data.get("buyer_name", ""),
            buyer_email=        order_data.get("buyer_email", ""),
            shipping_address=   order_data.get("shipping_address", ""),
            shipping_city=      order_data.get("shipping_city", ""),
            shipping_state=     order_data.get("shipping_state", ""),
            shipping_country=   order_data.get("shipping_country", ""),
            shipping_zip=       order_data.get("shipping_zip", ""),
            status=             order_data.get("status", "completed"),
            source=             order_data.get("source", "email_parser"),
            notes=              order_data.get("notes", ""),
        )

        db.add(sale)
        # db.add() queues the insert — not sent to DB yet

        db.commit()
        # db.commit() sends the INSERT to the database
        # If order_id already exists → IntegrityError raised here

        return True  # Successfully saved

    except Exception as e:
        db.rollback()
        # rollback() undoes any partial changes from this session
        # Important — leaves the database in a clean state

        error_msg = str(e).lower()
        if "unique" in error_msg or "duplicate" in error_msg:
            # This is expected — duplicate order, not a real error
            return False
        else:
            # Unexpected database error — log it
            logger.error(f"Database error saving order: {e}")
            return False

    finally:
        db.close()
        # finally block ALWAYS runs — even if exception occurred
        # Ensures connection is returned to the pool
        # Without this, connections leak and eventually exhaust


def _save_message_to_db(message_data: dict) -> bool:
    """Saves a buyer message to the database. Same pattern as _save_order_to_db."""
    db = SessionLocal()
    try:
        message = Message(
            message_id=  message_data["message_id"],
            platform=    message_data["platform"],
            buyer_name=  message_data.get("buyer_name", ""),
            buyer_email= message_data.get("buyer_email", ""),
            subject=     message_data.get("subject", ""),
            preview=     message_data.get("preview", ""),
            full_body=   message_data.get("full_body", ""),
            received_at= message_data.get("received_at", datetime.now()),
            is_read=     False,
            is_replied=  False,
        )

        db.add(message)
        db.commit()
        return True

    except Exception as e:
        db.rollback()
        error_msg = str(e).lower()
        if "unique" in error_msg or "duplicate" in error_msg:
            return False
        else:
            logger.error(f"Database error saving message: {e}")
            return False

    finally:
        db.close()


def _update_daily_stats(results: dict) -> None:
    """
    Updates the running daily statistics.
    Resets at midnight automatically.
    """
    global _daily_stats

    today = datetime.now(timezone.utc).date()

    # Reset if it's a new day
    if _daily_stats["last_reset"] != today:
        _daily_stats = {
            "orders_found":   0,
            "messages_found": 0,
            "emails_skipped": 0,
            "errors":         0,
            "last_reset":     today,
        }
        logger.info("Daily stats reset for new day")

    _daily_stats["orders_found"]   += results["orders_found"]
    _daily_stats["messages_found"] += results["messages_found"]
    _daily_stats["emails_skipped"] += results["emails_skipped"]
    _daily_stats["errors"]         += results["errors"]


def get_daily_stats() -> dict:
    """Returns today's accumulated statistics. Used by /metrics endpoint."""
    return _daily_stats.copy()