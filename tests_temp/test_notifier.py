# test_notifier.py
# Tests the full notification pipeline with real Telegram + email
# This is an INTEGRATION test — it uses real credentials and
# actually sends messages to verify end-to-end flow works.
#
# DIFFERENCE: unit test vs integration test
# Unit test:       tests one function in isolation (fake dependencies)
# Integration test: tests multiple components working together (real)
#
# We use BOTH:
# - Unit tests (test_email_parser.py) = fast, no credentials needed
# - Integration tests (this file) = slower, requires real credentials
#   but proves the full pipeline works end to end
#
# INTERVIEW POINT:
# "I wrote both unit tests for business logic and integration
#  tests for external service connections. Unit tests run in
#  CI on every commit (fast, no credentials). Integration tests
#  run manually to verify the real notification pipeline works."

import sys
import os
from datetime import datetime

sys.path.append(
    os.path.join(os.path.dirname(__file__), '..', 'backend')
)

from app.notifications.notifier import Notifier

# Sample data matching what the email parser produces
SAMPLE_ORDER = {
    "order_id":           "etsy_3456789012",
    "platform":           "etsy",
    "product_name":       "Custom Color Lithophane LED Night Light",
    "category":           "Lithophanes",
    "quantity":           1,
    "sale_price":         54.99,
    "platform_fee":       9.87,
    "net_revenue":        45.12,
    "buyer_name":         "Deepanshu Mehta",
    "shipping_city":      "Mumbai",
    "shipping_country":   "India",
    "shipping_address":   "123 Main Street, Mumbai",
    "order_date":         datetime.now(),
}

SAMPLE_MESSAGE = {
    "message_id": "etsy_msg_abc123",
    "platform":   "etsy",
    "buyer_name": "Sarah K.",
    "preview":    "Hi! Can I get this in a larger size? I need it for a gift.",
    "subject":    "Sarah K. sent you a message on Etsy",
}


def run_test(name, passed, details=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} | {name}")
    if details:
        print(f"       {details}")
    return passed


if __name__ == "__main__":
    print("=" * 55)
    print("Notifier Integration Test")
    print("Sending REAL messages to Telegram and email")
    print("=" * 55)

    notifier = Notifier()

    print("\n--- Test 1: Order alert ---")
    result = notifier.order_received(SAMPLE_ORDER)
    run_test(
        "Order alert sent (Telegram + Email)",
        result,
        "Check Telegram and Gmail inbox"
    )

    print("\n--- Test 2: Message alert ---")
    result = notifier.message_received(SAMPLE_MESSAGE)
    run_test(
        "Message alert sent (Telegram + Email)",
        result,
        "Check Telegram and Gmail inbox"
    )

    print("\n--- Test 3: Low stock alert ---")
    result = notifier.low_stock_warning(
        "Custom LED Lithophane",
        "etsy",
        1
    )
    run_test(
        "Low stock alert sent",
        result
    )

    print("\n--- Test 4: System error alert ---")
    result = notifier.system_error(
        "Test system alert",
        "This is a test — ignore this message"
    )
    run_test("System error alert sent (Telegram only)", result)

    print("\n--- Stats ---")
    stats = notifier.get_stats()
    print(f"Total sent:     {stats['total_sent']}")
    print(f"Telegram sent:  {stats['telegram_sent']}")
    print(f"Email sent:     {stats['email_sent']}")
    print(f"Failures:       {stats['failures']}")
    print(f"Success rate:   {stats['success_rate']}%")

    print("\n" + "=" * 55)
    if stats["failures"] == 0:
        print("✅ All notifications delivered successfully!")
        print("Check your Telegram and Gmail inbox now.")
    else:
        print(f"⚠️ {stats['failures']} notification(s) failed")
        print("Check logs above for details")
    print("=" * 55)