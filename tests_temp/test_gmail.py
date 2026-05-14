# test_gmail.py
# Credentials loaded from .env via config — no hardcoded values

import sys
import os
sys.path.append(
    os.path.join(os.path.dirname(__file__), '..', 'backend')
)

from app.core.config import settings
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

def send_email_alert(subject, body):
    """
    Sends email alert using Gmail SMTP.
    Credentials come from settings — loaded from .env file.
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = settings.GMAIL_ADDRESS
    msg["To"]      = settings.GMAIL_ADDRESS

    text_part = MIMEText(body, "plain")
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #333;">🪔 RiMitLayers Alert</h2>
        <div style="background: #f5f5f5; padding: 15px; border-radius: 8px;">
            {body.replace(chr(10), '<br>')}
        </div>
        <p style="color: #999; font-size: 12px; margin-top: 20px;">
            Sent by RiMitLayers Dashboard
        </p>
    </body>
    </html>
    """
    html_part = MIMEText(html_body, "html")
    msg.attach(text_part)
    msg.attach(html_part)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.GMAIL_ADDRESS, settings.GMAIL_APP_PASSWORD)
            server.sendmail(
                settings.GMAIL_ADDRESS,
                settings.GMAIL_ADDRESS,
                msg.as_string()
            )
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    print(f"Environment : {settings.ENVIRONMENT}")
    print(f"Gmail       : {settings.GMAIL_ADDRESS[:4]}****")  # mask it
    print("Sending test email...")

    success = send_email_alert(
        subject="✅ RiMitLayers — Email alerts working!",
        body=(
            "🎉 Email alert system working!\n\n"
            "Credentials loaded securely from .env file\n"
            "No hardcoded values in source code"
        )
    )

    if success:
        print("✅ Email sent! Check your inbox.")
    else:
        print("❌ Failed — check error above")