# test_scheduler.py
# Tests the scheduler starts, runs one poll cycle, and stops.
#
# NOTE: This test actually polls Gmail so you need:
# - Valid gmail_token.json (from our OAuth test)
# - Valid .env credentials
#
# The test runs ONE immediate poll then stops.
# Watch your Telegram — if you have unread Etsy/eBay emails
# you'll see them come through right now!

import sys
import os
import time

sys.path.append(
    os.path.join(os.path.dirname(__file__), '..', 'backend')
)

# Create database tables first
from app.models.database import create_tables
create_tables()

from app.core.scheduler import RiMitScheduler


def run_test(name, passed, details=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} | {name}")
    if details:
        print(f"       {details}")
    return passed


if __name__ == "__main__":
    print("=" * 55)
    print("Scheduler Test")
    print("Starting scheduler — will run ONE poll cycle")
    print("Watch your Telegram for any real alerts!")
    print("=" * 55)

    s = RiMitScheduler()

    # Test 1: Scheduler starts
    print("\n--- Test 1: Scheduler starts ---")
    s.start()
    run_test("Scheduler started", s.scheduler.running)

    # Test 2: Jobs are registered
    print("\n--- Test 2: Jobs registered ---")
    jobs = s.scheduler.get_jobs()
    run_test(
        f"Jobs registered: {len(jobs)}",
        len(jobs) >= 2,
        f"Jobs: {[j.name for j in jobs]}"
    )

    # Test 3: Wait for first poll to complete
    print("\n--- Test 3: First poll cycle ---")
    print("Waiting 30 seconds for first poll to complete...")
    print("(Watch your Telegram!)")
    time.sleep(30)

    status = s.get_status()
    ran = status["stats"]["total_runs"] > 0
    run_test(
        "First poll cycle completed",
        ran,
        f"Runs: {status['stats']['total_runs']} | "
        f"Daily orders: {status['daily']['orders_found']} | "
        f"Daily messages: {status['daily']['messages_found']}"
    )

    # Test 4: Manual trigger works
    print("\n--- Test 4: Manual poll trigger ---")
    result = s.trigger_manual_poll()
    run_test(
        "Manual poll trigger works",
        "error" not in result,
        f"Result: {result}"
    )

    # Test 5: Clean shutdown
    print("\n--- Test 5: Clean shutdown ---")
    s.stop()
    run_test(
        "Scheduler stopped cleanly",
        not s.scheduler.running
    )

    print("\n" + "=" * 55)
    print("✅ Scheduler test complete!")
    print(
        f"Stats: "
        f"Runs={status['stats']['total_runs']} | "
        f"Success={status['stats']['successful_runs']} | "
        f"Failed={status['stats']['failed_runs']}"
    )
    print("=" * 55)