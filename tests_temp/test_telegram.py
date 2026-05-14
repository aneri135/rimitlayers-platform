# test_telegram.py
# Purpose: Verify our Telegram bot can send messages to our phone
# We test this NOW before writing any real code so we know the credentials work

import sys
import os

sys.path.append(
    os.path.join(os.path.dirname(__file__), '..', 'backend')
)

from app.core.config import settings
import urllib.request
import json

def send_telegram_message(text):
    """
    Sends a message to our Telegram chat using the Bot API.
    Credentials come from settings object which reads from .env
    """
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode("utf-8"))
        return result

if __name__ == "__main__":
    print(f"Environment : {settings.ENVIRONMENT}")
    print(f"Telegram ID : {settings.TELEGRAM_CHAT_ID[:4]}****")  # mask it
    print("Sending test message...")

    result = send_telegram_message(
        "🎉 <b>RiMitLayers Bot is working!</b>\n\n"
        "✅ Credentials loaded from .env\n"
        "✅ Telegram connection confirmed\n"
        "🛒 Ready to receive order alerts"
    )

    if result.get("ok"):
        print("✅ Success! Check your Telegram.")
    else:
        print("❌ Failed:", result)
