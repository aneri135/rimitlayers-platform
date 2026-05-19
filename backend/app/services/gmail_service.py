# backend/app/services/gmail_service.py
#
# PURPOSE: The ONLY file that talks directly to Gmail API
#
# ANALOGY: Think of this as the "postman" for our system.
# Its only job is to go to the Gmail mailbox, collect the mail,
# and hand it to email_parser.py. It knows nothing about what
# the emails contain or what to do with them.
#
# WHY ISOLATE GMAIL API HERE?
# If Google changes their API tomorrow, we only update THIS file.
# The rest of the system never changes. This is called the
# "Adapter Pattern" — wrapping an external service in your own
# interface so the rest of your code stays stable.


import os
import sys
import base64
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional

# Google's official Python libraries
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Add backend to path so we can import our config
sys.path.append(
    os.path.join(os.path.dirname(__file__), '..', '..', '..')
)
from app.core.config import settings

# Set up logging for this module
# logging.getLogger(__name__) creates a logger named after this file
# e.g. "app.services.gmail_service"
# This lets us filter logs by module in production
logger = logging.getLogger(__name__)

# SCOPES = what permissions we ask Google for
# We only request exactly what we need — principle of least privilege
# gmail.readonly = read emails (for parsing Etsy/eBay notifications)
# gmail.send = send emails (for alert emails to ourselves)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    # gmail.modify includes read + mark as read + move to labels
    # It does NOT allow deleting emails or accessing Drive/Calendar
    # More permissive than readonly but still very limited
    # We need this to mark processed emails as read so we
    # don't process the same email on every poll cycle

    "https://www.googleapis.com/auth/gmail.send",
    # Required for sending email alerts to ourselves
]


class GmailService:
    
    #Wrapper around Google's Gmail API.

    #WHY A CLASS INSTEAD OF FUNCTIONS?
    #The Gmail service object (self.service) is expensive to create —
    #it involves OAuth token validation and an HTTP connection.
    #By storing it in a class instance, we create it ONCE and reuse
    #it for every email check. Functions would recreate it every call.

    #This is called "connection pooling" at a simple level.


    def __init__(self):
        # self.service starts as None — it's created lazily
        # "Lazy initialisation" = don't create until first needed
        # This means importing this file doesn't immediately
        # open a network connection
        self.service = None
        self._authenticate()

    def _authenticate(self):
    
       # Handles OAuth2 authentication with Gmail.

       # The underscore prefix (_authenticate) is a Python convention
       # meaning "this is a private method — only call from inside
       # this class". External code calls get_emails(), not _authenticate().

        #TOKEN FLOW (important to understand):
        #1. First run ever → no token file exists
        #   → token saved to gmail_token.json
        #2. Subsequent runs → token file exists + valid
        #   → loads token silently (no browser)
        #3. Token expired → has refresh_token
        #   → automatically gets new token (no browser)
        #4. Refresh token also expired (rare, ~6 months)
        #   → opens browser again for fresh login
        
        creds = None

        # Step 1: Try to load existing saved token
        # os.path.exists checks if the file is there without crashing
        if os.path.exists(settings.GMAIL_TOKEN_FILE):
            logger.info("Loading existing Gmail token...")
            creds = Credentials.from_authorized_user_file(
                settings.GMAIL_TOKEN_FILE,
                SCOPES
            )
            # Credentials.from_authorized_user_file reads the JSON token
            # file and creates a Credentials object from it

        # Step 2: Handle missing or expired credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                # Token exists but expired — refresh it silently
                # This happens automatically, no user action needed
                logger.info("Token expired — refreshing...")
                creds.refresh(Request())
                # Request() is Google's HTTP transport object
                # creds.refresh() calls Google to get a fresh token
            else:
                # No token at all — first time setup
                # InstalledAppFlow handles the browser-based login
                logger.info("First time auth — opening browser...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    settings.GMAIL_CREDENTIALS_FILE,
                    SCOPES
                )
                # run_local_server opens browser, starts local HTTP server
                # to receive the OAuth callback from Google
                # port=0 means "pick any available port automatically"
                creds = flow.run_local_server(port=0)

            # Save token for next time
            # to_json() converts the Credentials object to JSON string
            with open(settings.GMAIL_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
            logger.info(f"Token saved to {settings.GMAIL_TOKEN_FILE}")

        # Step 3: Build the Gmail API service object
        # build("gmail", "v1", ...) creates a client for Gmail API v1
        # This is the object we use to make all Gmail API calls
        self.service = build("gmail", "v1", credentials=creds)
        logger.info("Gmail service authenticated successfully")

    def get_unread_emails(
        self,
        from_addresses: List[str] = None,
        max_results: int = 50,
        since_minutes: int = 10  # look back 10 minutes to catch any missed
    ) -> List[Dict]:
        """
        Fetches emails — both unread AND recently received.

        WHY LOOK AT READ EMAILS TOO?
        If you manually read an Etsy email before the 5-min poll runs,
        the order would never reach your database.
        Solution: we search for emails received in the last 10 minutes
        regardless of read status, then check our database to see if
        we already recorded it (using the unique order_id constraint).
        If it's already in the database — skip. If not — process it.

        This means:
        - You read the email manually → still gets recorded in DB
        - No Telegram alert sent for already-processed orders (DB check)
        - Dashboard always has complete data

        INTERVIEW POINT:
        "I discovered that polling only unread emails caused a data gap
        when the user manually read an email before the poll ran.
        I fixed this by searching emails received in the last N minutes
        regardless of read status, then using the database unique
        constraint as the deduplication mechanism. If an order_id
        already exists in the database, it's skipped silently."
        """
        if not self.service:
            return []

        try:
            query_parts = ["in:inbox"]
            # Remove "is:unread" — we now check ALL recent emails
            # Database unique constraint handles deduplication

            # Add time filter — only emails from last 10 minutes
            # Gmail search supports 'newer_than:Xm' syntax
            query_parts.append(f"newer_than:{since_minutes}m")

            if from_addresses:
                from_query = " OR ".join(
                    [f"from:{addr}" for addr in from_addresses]
                )
                query_parts.append(f"({from_query})")

            query = " ".join(query_parts)
            logger.info(f"Gmail search query: {query}")

            result = self.service.users().messages().list(
                userId="me",
                q=query,
                maxResults=max_results
            ).execute()

            messages = result.get("messages", [])

            if not messages:
                logger.info("No recent emails found")
                return []

            logger.info(f"Found {len(messages)} recent emails to check")

            emails = []
            for msg in messages:
                email_data = self._get_email_details(msg["id"])
                if email_data:
                    emails.append(email_data)

            return emails

        except HttpError as e:
            logger.error(f"Gmail API error: {e.status_code} — {e.reason}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching emails: {e}")
            return []
    
    def _get_email_details(self, message_id: str) -> Optional[Dict]:
        """
        Fetches full content of a single email by its ID.

        WHY SEPARATE FROM get_unread_emails?
        Gmail API design: listing gives IDs, fetching gives content.
        Two separate API calls. We separate them in code too —
        clean, testable, single responsibility.

        format="full" means give us everything:
        headers (From, Subject, Date) + body content

        MIME STRUCTURE EXPLAINED:
        Email bodies are not plain text strings. They use MIME format:
        - multipart/alternative: email has both plain text AND HTML
          versions. Email clients pick the best one they support.
        - text/plain: plain text version
        - text/html: HTML formatted version (what you see)
        We extract the plain text version — easier to parse reliably.

        BASE64 EXPLAINED:
        Gmail API returns email body as base64-encoded bytes.
        Base64 converts binary data to safe ASCII text for transport.
        We decode it back to readable text.
        base64.urlsafe_b64decode() handles Gmail's URL-safe variant.
        """
        try:
            msg = self.service.users().messages().get(
                userId="me",
                id=message_id,
                format="full"
                # "full" = complete message with headers and body
                # alternatives: "metadata" (headers only), "raw" (RFC 2822)
            ).execute()

            # Extract headers into a dictionary for easy access
            headers = {}
            for header in msg.get("payload", {}).get("headers", []):
                # Each header is {"name": "From", "value": "..."}
                # We convert to {"From": "..."} for easy lookup
                headers[header["name"]] = header["value"]

            # Extract email body
            body = self._extract_body(msg.get("payload", {}))

            # Parse the date string into a Python datetime object
            date_str = headers.get("Date", "")
            email_date = self._parse_date(date_str)

            return {
                "id":          message_id,
                "from":        headers.get("From", ""),
                "subject":     headers.get("Subject", ""),
                "date":        email_date,
                "body":        body,
                "raw_headers": headers,
            }

        except Exception as e:
            logger.error(f"Error fetching email {message_id}: {e}")
            return None

    def _extract_body(self, payload: Dict) -> str:
        """
        Extracts plain text body from a MIME email payload.

        MIME STRUCTURE can be:
        1. Simple: payload has body directly (text/plain)
        2. Multipart: payload has "parts" list, each part has body
           (common for emails with both plain text and HTML)

        We prefer text/plain because:
        - HTML has tags that interfere with our regex parsing
        - Plain text is consistent across email clients
        - Easier to extract prices, names, addresses reliably

        WHY RECURSIVE?
        Multipart emails can be nested:
        multipart/alternative
          -> multipart/related
               -> text/plain
               -> text/html
        We recurse into nested parts to find text/plain anywhere.
        """
        body = ""

        # Case 1: This payload has a body directly
        if "body" in payload and payload["body"].get("data"):
            # data is base64url encoded — decode to get text
            encoded = payload["body"]["data"]
            decoded_bytes = base64.urlsafe_b64decode(
                encoded + "=="  # padding — base64 requires length % 4 == 0
            )
            body = decoded_bytes.decode("utf-8", errors="replace")
            # errors="replace" = if a byte can't be decoded,
            # replace with ? rather than crashing
            return body

        # Case 2: Multipart — look in parts
        if "parts" in payload:
            for part in payload["parts"]:
                mime_type = part.get("mimeType", "")

                if mime_type == "text/plain":
                    # Found plain text — extract and return immediately
                    if part.get("body", {}).get("data"):
                        encoded = part["body"]["data"]
                        decoded = base64.urlsafe_b64decode(encoded + "==")
                        return decoded.decode("utf-8", errors="replace")

                elif mime_type.startswith("multipart/"):
                    # Nested multipart — recurse into it
                    nested = self._extract_body(part)
                    if nested:
                        return nested

        return body  # Return empty string if nothing found

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        
     # Converts Gmail date string to Python datetime object.

    #PROBLEM WE SOLVED:
    #Real-world email date strings are messy. They can have:
    #- Double spaces: "Thu,  2 Apr 2026" (single digit day)
    #- Extra timezone labels: "+0000 (UTC)" at the end
    #- Missing day names: "2 Apr 2026 21:03:24 +0000"
    #- Different timezone formats: "+0000" vs "UTC" vs "GMT"

    #SOLUTION: Clean the string first, then try multiple formats.
    #Pre-processing handles the messiness before format matching.

    #WHY NOT USE email.utils.parsedate()?
    #Python's standard library has email.utils.parsedate() which
   # handles RFC 2822 dates. We use it as our primary parser
    #because it handles ALL these edge cases automatically.
    #Our manual formats are a fallback only.


        if not date_str:
            return datetime.now(timezone.utc)

    # ---- APPROACH 1: Use Python's built-in email date parser ----
    # email.utils.parsedate_to_datetime() implements RFC 2822
    # the exact standard that email date headers follow
    # This is the most robust approach
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str.strip())
        except Exception:
            pass  # Fall through to manual parsing

    # ---- APPROACH 2: Clean the string then try manual formats ----
    # Some date strings have quirks that even parsedate can't handle
    # We clean them up first

        import re

        cleaned = date_str.strip()

    # Remove trailing timezone labels like "(UTC)", "(EST)", "(GMT+0)"
    # These appear AFTER the numeric offset and confuse strptime
    # Example: "+0000 (UTC)" → "+0000"
        cleaned = re.sub(r'\s*\([^)]+\)\s*$', '', cleaned).strip()

    # Normalise multiple spaces to single space
    # Example: "Thu,  2 Apr" → "Thu, 2 Apr"
    # This fixes single-digit days which some servers pad with space
        cleaned = re.sub(r' +', ' ', cleaned)

    # Try formats on the cleaned string
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",    # Thu, 02 Apr 2026 21:03:24 +0000
            "%a, %d %b %Y %H:%M:%S %Z",    # Thu, 02 Apr 2026 21:03:24 UTC
            "%d %b %Y %H:%M:%S %z",        # 02 Apr 2026 21:03:24 +0000
            "%d %b %Y %H:%M:%S %Z",        # 02 Apr 2026 21:03:24 UTC
            "%a, %d %b %Y %H:%M:%S",       # Thu, 02 Apr 2026 21:03:24 (no tz)
        ]

        for fmt in formats:
            try:
                return datetime.strptime(cleaned, fmt)
            except ValueError:
                continue

    # ---- APPROACH 3: Extract date parts with regex ----
    # Last resort — pull out the parts we care about manually
    # Works even if the format is completely non-standard
        try:
            months = {
                "jan": 1, "feb": 2, "mar": 3,  "apr": 4,
                "may": 5, "jun": 6, "jul": 7,  "aug": 8,
                "sep": 9, "oct": 10,"nov": 11, "dec": 12
            }

        # Match: optional "Day, " + day + month + year + time
            match = re.search(
                r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\s+'
                r'(\d{2}):(\d{2}):(\d{2})',
                date_str
            )
            if match:
                day, mon, year, hour, minute, sec = match.groups()
                month_num = months.get(mon.lower())
                if month_num:
                    return datetime(
                        int(year), month_num, int(day),
                        int(hour), int(minute), int(sec),
                        tzinfo=timezone.utc
                    )
        except Exception:
            pass

    # Complete fallback — use current time and log a warning
        logger.warning(
            f"Could not parse date after all attempts: '{date_str}' "
            f"— using current time as fallback"
        )
        return datetime.now(timezone.utc)

    def mark_as_read(self, message_id: str) -> bool:
        """
        Marks email as read after processing.
        Now optional — deduplication happens via database unique constraint.
        Still useful to keep inbox clean.
        """
        try:
            self.service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]}
            ).execute()
            return True
        except Exception as e:
            # Non-critical — log but don't fail
            logger.debug(f"Could not mark {message_id} as read: {e}")
            return False