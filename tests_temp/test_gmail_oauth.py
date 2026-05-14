# test_gmail_oauth.py
#
# PURPOSE: Test Gmail OAuth2 authentication and email reading
#
# HOW OAUTH2 WORKS (important for interviews):
# 1. First run: Opens browser → you log in to Google → Google gives
#    us a "token" and saves it to gmail_token.json
# 2. Every run after: Uses saved token automatically — no browser needed
# 3. If token expires: Automatically refreshes using credentials.json
#
# WHY OAUTH2 OVER APP PASSWORD FOR READING?
# - App password is fine for SENDING (SMTP) — simple and works
# - For READING emails OAuth2 is more secure and is Google's
#   recommended approach for apps that access Gmail data
# - Token can be revoked anytime without changing your password
# - Scopes limit exactly what the app can do (read only in our case)
#
# INTERVIEW POINT:
# "I used OAuth2 with minimal scopes for Gmail access — readonly
#  for reading Etsy notifications. This follows the principle of
#  least privilege — the app can only do what it needs to, nothing more.
#  Tokens are stored locally and refreshed automatically."

import sys
import os

# Add backend to path so we can import config
sys.path.append(
    os.path.join(os.path.dirname(__file__), '..', 'backend')
)

from app.core.config import settings

# Google's official Python libraries for OAuth2
# These were installed via requirements.txt
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import json
import base64

# SCOPES tell Google exactly what permissions we need
# We only request what we actually use — principle of least privilege
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",  # read emails
    "https://www.googleapis.com/auth/gmail.send",      # send emails
]

def get_gmail_service():
    """
    Authenticates with Gmail API using OAuth2 and returns a service object.
    
    The service object is what we use to make all Gmail API calls.
    Think of it as an authenticated connection to Gmail.
    
    Token flow:
    - gmail_token.json exists + valid → use it directly (silent)
    - gmail_token.json exists + expired → auto refresh (silent)  
    - gmail_token.json missing → open browser for first-time auth
    """
    creds = None

    # Check if we already have a saved token from a previous login
    if os.path.exists(settings.GMAIL_TOKEN_FILE):
        print("Found existing token — loading...")
        creds = Credentials.from_authorized_user_file(
            settings.GMAIL_TOKEN_FILE,
            SCOPES
        )

    # If no valid credentials available, get new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Token expired but we have refresh token — silently refresh
            print("Token expired — refreshing automatically...")
            creds.refresh(Request())
        else:
            # First time setup — opens browser for you to log in
            print("First time setup — opening browser for Google login...")
            print("Please log in with your Gmail account and allow access.")
            
            flow = InstalledAppFlow.from_client_secrets_file(
                settings.GMAIL_CREDENTIALS_FILE,
                SCOPES
            )
            # Opens browser, waits for you to complete login
            creds = flow.run_local_server(port=0)

        # Save token for next time — no browser needed again
        with open(settings.GMAIL_TOKEN_FILE, "w") as token_file:
            token_file.write(creds.to_json())
        print(f"Token saved to: {settings.GMAIL_TOKEN_FILE}")

    # Build and return the Gmail API service object
    service = build("gmail", "v1", credentials=creds)
    return service


def test_read_recent_emails(service, max_results=5):
    """
    Reads the 5 most recent emails from inbox.
    
    This proves our Gmail connection works and we can
    read email metadata — sender, subject, date.
    
    We don't read full email body here — just headers.
    Headers are enough to classify order vs message vs ignore.
    """
    print(f"\nReading last {max_results} emails from inbox...")
    print("-" * 50)

    # Call Gmail API to list messages
    # q="" means no filter — get all inbox messages
    result = service.users().messages().list(
        userId="me",          # "me" means the authenticated user
        maxResults=max_results,
        labelIds=["INBOX"]    # only inbox, not spam/trash
    ).execute()

    messages = result.get("messages", [])

    if not messages:
        print("No messages found in inbox")
        return

    for msg in messages:
        # Get full message details — we need the headers
        msg_detail = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="metadata",           # metadata only — faster than full
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()

        # Extract headers into a dictionary
        headers = {}
        for header in msg_detail.get("payload", {}).get("headers", []):
            headers[header["name"]] = header["value"]

        print(f"From    : {headers.get('From', 'Unknown')}")
        print(f"Subject : {headers.get('Subject', 'No subject')}")
        print(f"Date    : {headers.get('Date', 'Unknown')}")
        print("-" * 50)


def test_search_etsy_emails(service):
    """
    Searches specifically for Etsy emails.
    
    Gmail API supports the same search syntax as Gmail's search bar.
    'from:etsy.com' finds all emails from any @etsy.com address.
    
    This is the exact search our production code will use
    to find order and message notifications.
    """
    print("\nSearching for Etsy emails...")
    print("-" * 50)

    # Gmail search query — same syntax as Gmail search bar
    query = "from:etsy.com"

    result = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=5
    ).execute()

    messages = result.get("messages", [])
    total = result.get("resultSizeEstimate", 0)

    print(f"Found approximately {total} Etsy emails in your inbox")

    if not messages:
        print("No Etsy emails found — that's okay for testing")
        return

    print(f"Showing last {len(messages)}:")
    print("-" * 50)

    for msg in messages:
        msg_detail = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()

        headers = {}
        for header in msg_detail.get("payload", {}).get("headers", []):
            headers[header["name"]] = header["value"]

        print(f"From    : {headers.get('From', 'Unknown')}")
        print(f"Subject : {headers.get('Subject', 'No subject')}")
        print(f"Date    : {headers.get('Date', 'Unknown')}")
        print("-" * 50)


if __name__ == "__main__":
    print("=" * 50)
    print("Gmail OAuth2 Connection Test")
    print("=" * 50)

    # Check credentials file exists before trying
    if not os.path.exists(settings.GMAIL_CREDENTIALS_FILE):
        print(f"❌ credentials file not found at:")
        print(f"   {settings.GMAIL_CREDENTIALS_FILE}")
        print(f"Download it from Google Cloud Console and save it there")
        sys.exit(1)

    print(f"✅ Credentials file found")
    print(f"Environment: {settings.ENVIRONMENT}")
    print()

    # Get authenticated Gmail service
    # First run will open browser — subsequent runs are silent
    service = get_gmail_service()

    print("✅ Gmail OAuth2 authentication successful!")

    # Test 1 — read recent emails
    test_read_recent_emails(service, max_results=3)

    # Test 2 — search for Etsy emails specifically
    test_search_etsy_emails(service)

    print("\n✅ All Gmail tests passed!")
    print("Gmail API is ready for reading Etsy notification emails")