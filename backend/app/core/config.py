# backend/app/core/config.py
#
# PURPOSE: Central configuration — single source of truth for all settings
#
# HOW IT WORKS:
# 1. python-dotenv reads backend/.env file
# 2. Values are loaded into os.environ (environment variables)
# 3. This config class reads from os.environ with safe defaults
# 4. Every other file imports from THIS file — never from os.environ directly
#
# WHY THIS PATTERN?
# - One place to change settings
# - Easy to see ALL config in one file
# - If a required variable is missing, it fails loudly at startup
#   rather than silently failing later during a real order
#
# INTERVIEW POINT:
# "I used a centralised settings pattern — all configuration is
#  loaded once at startup and validated. If any required environment
#  variable is missing the app refuses to start with a clear error
#  message rather than failing mysteriously at runtime."

import os
from pathlib import Path
from dotenv import load_dotenv

# Find the .env file — it sits in the backend/ folder
# Path(__file__) = this file (config.py)
# .parent = app/core/ folder
# .parent.parent = app/ folder
# .parent.parent.parent = backend/ folder
BASE_DIR = Path(__file__).parent.parent.parent
ENV_FILE = BASE_DIR / ".env"

# Load the .env file into os.environ
# override=False means existing env vars take priority
# (important for Docker/production where vars are set differently)
load_dotenv(ENV_FILE, override=False)

class Settings:
    """
    All application settings in one place.
    
    Each setting reads from environment variable with a fallback default.
    os.environ.get("KEY", "default") — returns default if KEY not set.
    os.environ["KEY"] — raises KeyError if KEY not set (for required fields).
    
    We use .get() with None default for optional settings,
    and direct access ["KEY"] for required settings that must exist.
    """

    def __init__(self):
        # --- APP ---
        self.ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
        self.POLL_INTERVAL_MINUTES = int(
            os.environ.get("POLL_INTERVAL_MINUTES", "5")
        )

        # --- TELEGRAM ---
        self.TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

        # --- GMAIL SMTP (sending alerts) ---
        self.GMAIL_ADDRESS      = os.environ.get("GMAIL_ADDRESS", "")
        self.GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

        # --- GMAIL API (reading Etsy/eBay notification emails) ---
        self.GMAIL_CREDENTIALS_FILE = os.environ.get(
            "GMAIL_CREDENTIALS_FILE", 
            str(BASE_DIR / "gmail_credentials.json")
        )
        self.GMAIL_TOKEN_FILE = os.environ.get(
            "GMAIL_TOKEN_FILE",
            str(BASE_DIR / "gmail_token.json")
        )

        # --- ETSY (kept for future use) ---
        self.ETSY_API_KEY       = os.environ.get("ETSY_API_KEY", "")
        self.ETSY_SHOP_ID       = os.environ.get("ETSY_SHOP_ID", "")
        self.ETSY_SHARED_SECRET = os.environ.get("ETSY_SHARED_SECRET", "")

        # --- EBAY ---
        self.EBAY_APP_ID    = os.environ.get("EBAY_APP_ID", "")
        self.EBAY_CERT_ID   = os.environ.get("EBAY_CERT_ID", "")
        self.EBAY_DEV_ID    = os.environ.get("EBAY_DEV_ID", "")
        self.EBAY_AUTH_TOKEN = os.environ.get("EBAY_AUTH_TOKEN", "")

        # --- STRIPE ---
        self.STRIPE_SECRET_KEY      = os.environ.get("STRIPE_SECRET_KEY", "")
        self.STRIPE_WEBHOOK_SECRET  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

        # --- AI ---
        self.ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

    def validate(self):
        """
        Call this at app startup to catch missing required settings early.
        
        WHY: Better to fail loudly at startup than silently during
        an important order notification. This is called "fail fast" —
        a key reliability principle in SRE.
        
        INTERVIEW POINT:
        "I implemented a validate() method that runs at startup and
        checks all required credentials are present. This follows the
        fail-fast principle — surface problems immediately rather than
        letting them cause silent failures in production."
        """
        errors = []

        # Telegram is required — all alerts go through it
        if not self.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN is missing")
        if not self.TELEGRAM_CHAT_ID:
            errors.append("TELEGRAM_CHAT_ID is missing")

        # Gmail is required — both for sending and reading emails
        if not self.GMAIL_ADDRESS:
            errors.append("GMAIL_ADDRESS is missing")
        if not self.GMAIL_APP_PASSWORD:
            errors.append("GMAIL_APP_PASSWORD is missing")

        if errors:
            raise ValueError(
                f"\n\n❌ Missing required environment variables:\n"
                + "\n".join(f"  - {e}" for e in errors)
                + f"\n\nCheck your .env file at: {ENV_FILE}\n"
            )

        print(f"✅ Config loaded — environment: {self.ENVIRONMENT}")
        return True


# Create a single instance — imported everywhere else
# This is the Singleton pattern — one shared instance across the whole app
settings = Settings()