# test_email_parser.py
# Tests the email parser WITHOUT needing a real Gmail connection
# We create fake email objects to test each layer independently
#
# WHY TEST WITHOUT REAL EMAILS?
# Real emails require Gmail connection, credentials, and actual
# Etsy orders to exist. Unit tests should work offline and fast.
# We simulate emails by creating dictionaries that look exactly
# like what GmailService returns — this is called "mocking".


import sys
import os
from datetime import datetime

sys.path.append(
    os.path.join(os.path.dirname(__file__), '..', 'backend')
)

from app.services.email_parser import EmailParser, EmailType
from app.services.etsy_parser import EtsyParser
from app.services.ebay_parser import EbayParser

# ============================================================
# SAMPLE EMAILS
# These simulate what GmailService.get_unread_emails() returns
# Based on real Etsy and eBay email formats
# ============================================================

SAMPLE_ETSY_ORDER_EMAIL = {
    "id": "gmail_msg_001",
    "from": "transaction@etsy.com",
    "subject": "You made a sale on Etsy - Ship by May 23 - [$26.31, Order #4067696529]",
    "date": datetime.now(),
    "body": """
Congratulations on your Etsy sale of 1 item.
Your order number is: 4067696529

Order details

Payment method                    Shipping address
Paid via Etsy Payments on         Leny Yoder
May 19, 2026                      34319 Columbine Trl E
                                  ELIZABETH, CO 80107-7869
                                  United States

Modern Spiral 3D Printed Decorative Vase - Sculptural Home Decor - Desk, Coffee Table, Shelf Centerpiece
Shop: RiMitLayers
Transaction ID: 5084173437
Quantity: 1
Price: $21.99
Returns and exchanges accepted within 30 days of delivery

Item total:     $21.99
Discount:       -$3.30
Subtotal:       $18.69
Shipping:       $6.36
Sales tax:      $0.98

Order total:    $26.31

etsy.com/your/orders/4067696529
    """
}

SAMPLE_ETSY_MESSAGE_EMAIL = {
    "id": "gmail_msg_002",
    "from": "noreply@mail.etsy.com",
    "subject": "Sarah K. sent you a message on Etsy",
    "date": datetime.now(),
    "body": """
    Sarah K. sent you a message on Etsy.

    Message: Hi! Can I get this in a larger size?
    I need it for a gift and wanted to know if custom
    sizes are available.

    Reply at etsy.com/conversations/12345
    """
}

SAMPLE_EBAY_ORDER_EMAIL = {
    "id": "gmail_msg_003",
    "from": "ebay@ebay.com",
    "subject": "You sold: Halloween Skull Tealight Lantern",
    "date": datetime.now(),
    "body": """
    Great news! You sold an item.

    Sold: Halloween Skull Tealight Lantern
    Sale price: $14.99
    Quantity: 1
    Buyer: mark_buyer123

    Order ID: 123456789012

    Ship to:
    Mark Brown
    456 Oak Avenue
    London, UK

    View order at ebay.com/orders/123456789012
    """
}

SAMPLE_PHISHING_EMAIL = {
    "id": "gmail_msg_004",
    "from": "noreply@fake-etsy-support.com",
    "subject": "You made a sale! Urgent action required",
    "date": datetime.now(),
    "body": """
    You have received an order! Click here to claim your money.
    Login at http://etsy-support-fake.com/login
    """
}

SAMPLE_NEWSLETTER_EMAIL = {
    "id": "gmail_msg_005",
    "from": "hello@etsy.com",
    "subject": "10 tips to grow your Etsy shop this season",
    "date": datetime.now(),
    "body": "Here are our top tips for Etsy sellers..."
}


def run_test(name: str, passed: bool, details: str = ""):
    """Simple test runner — prints pass/fail with details."""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} | {name}")
    if not passed and details:
        print(f"       Details: {details}")
    return passed


def test_email_classifier():
    print("\n=== Testing EmailParser (3-layer classification) ===")
    parser = EmailParser()
    all_passed = True

    # Test 1: Real Etsy order email should be classified as ORDER
    result = parser.classify(SAMPLE_ETSY_ORDER_EMAIL)
    passed = (
        result.email_type == EmailType.ORDER and
        result.platform == "etsy" and
        result.confidence > 0.9
    )
    all_passed &= run_test(
        "Etsy order email → classified as ORDER",
        passed,
        f"Got: type={result.email_type}, platform={result.platform}, confidence={result.confidence}"
    )

    # Test 2: Etsy message email should be classified as MESSAGE
    result = parser.classify(SAMPLE_ETSY_MESSAGE_EMAIL)
    passed = (
        result.email_type == EmailType.MESSAGE and
        result.platform == "etsy"
    )
    all_passed &= run_test(
        "Etsy message email → classified as MESSAGE",
        passed,
        f"Got: type={result.email_type}, platform={result.platform}"
    )

    # Test 3: Phishing email should be IGNORED at Layer 1
    result = parser.classify(SAMPLE_PHISHING_EMAIL)
    passed = (
        result.email_type == EmailType.IGNORE and
        result.confidence == 0.0  # Layer 1 rejected — zero confidence
    )
    all_passed &= run_test(
        "Phishing email → IGNORED at Layer 1 (wrong domain)",
        passed,
        f"Got: type={result.email_type}, confidence={result.confidence}"
    )

    # Test 4: Newsletter email should be IGNORED at Layer 2
    result = parser.classify(SAMPLE_NEWSLETTER_EMAIL)
    passed = (
        result.email_type == EmailType.IGNORE and
        result.platform == "etsy"
        # platform is etsy (Layer 1 passed) but type is IGNORE (Layer 2 failed)
    )
    all_passed &= run_test(
        "Newsletter email → IGNORED at Layer 2 (subject not matched)",
        passed,
        f"Got: type={result.email_type}, platform={result.platform}"
    )

    # Test 5: eBay order email
    result = parser.classify(SAMPLE_EBAY_ORDER_EMAIL)
    passed = (
        result.email_type == EmailType.ORDER and
        result.platform == "ebay"
    )
    all_passed &= run_test(
        "eBay order email → classified as ORDER",
        passed,
        f"Got: type={result.email_type}, platform={result.platform}"
    )

    return all_passed


def test_etsy_parser():
    print("\n=== Testing EtsyParser (data extraction) ===")
    parser = EtsyParser()
    all_passed = True

    # Test order parsing
    result = parser.parse_order_email(SAMPLE_ETSY_ORDER_EMAIL)

    passed = result is not None
    all_passed &= run_test("Etsy order email parsed (not None)", passed)

    if result:
        passed = result["platform"] == "etsy"
        all_passed &= run_test("Platform = etsy", passed)

        passed = round(result["sale_price"], 2) == round(21.99, 2)
        all_passed &= run_test(
            f"Sale price extracted = $21.99",
            passed,
            f"Got: ${result.get('sale_price')}"
        )

        passed = result["product_name"] is not None and len(result["product_name"]) > 3
        all_passed &= run_test(
            "Product name extracted",
            passed,
            f"Got: {result.get('product_name')}"
        )

        passed = result["platform_fee"] > 0
        all_passed &= run_test(
            f"Platform fee calculated = ${result.get('platform_fee')}",
            passed
        )

        passed = result["net_revenue"] == round(
            result["sale_price"] - result["platform_fee"], 2
        )
        all_passed &= run_test(
            f"Net revenue calculated = ${result.get('net_revenue')}",
            passed
        )

        passed = result["category"] in ["Lithophanes", "Lanterns", "Vases", "Other"]
        all_passed &= run_test(
            f"Category guessed = {result.get('category')}",
            passed
        )

    # Test message parsing
    msg_result = parser.parse_message_email(SAMPLE_ETSY_MESSAGE_EMAIL)
    passed = msg_result is not None
    all_passed &= run_test("Etsy message email parsed (not None)", passed)

    if msg_result:
        passed = msg_result["platform"] == "etsy"
        all_passed &= run_test("Message platform = etsy", passed)

        passed = msg_result["preview"] is not None and len(msg_result["preview"]) > 0
        all_passed &= run_test(
            "Message preview extracted",
            passed,
            f"Preview: {msg_result.get('preview', '')[:60]}..."
        )

    return all_passed


def test_ebay_parser():
    print("\n=== Testing EbayParser (data extraction) ===")
    parser = EbayParser()
    all_passed = True

    result = parser.parse_order_email(SAMPLE_EBAY_ORDER_EMAIL)

    passed = result is not None
    all_passed &= run_test("eBay order email parsed (not None)", passed)

    if result:
        passed = result["platform"] == "ebay"
        all_passed &= run_test("Platform = ebay", passed)

        passed = result["sale_price"] == 14.99
        all_passed &= run_test(
            f"Sale price extracted = $14.99",
            passed,
            f"Got: ${result.get('sale_price')}"
        )

        passed = result["platform_fee"] > 0
        all_passed &= run_test(
            f"eBay fee calculated = ${result.get('platform_fee')}",
            passed
        )

    return all_passed


if __name__ == "__main__":
    print("=" * 55)
    print("Email Parser Test Suite")
    print("Testing without real Gmail connection (unit tests)")
    print("=" * 55)

    results = []
    results.append(test_email_classifier())
    results.append(test_etsy_parser())
    results.append(test_ebay_parser())

    print("\n" + "=" * 55)
    if all(results):
        print("✅ All tests passed!")
        print("Email parser is ready for real Gmail emails.")
    else:
        print("❌ Some tests failed — check output above")
    print("=" * 55)