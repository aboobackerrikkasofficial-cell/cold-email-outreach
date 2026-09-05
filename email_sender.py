"""
Sends real emails through the Gmail API (OAuth2) as hello.aboobackerrikkas@gmail.com.

One-time setup required (see README.md):
  1. Create OAuth credentials in Google Cloud Console, download as credentials.json.
  2. First run opens a browser to authorize - after that, token.json is saved and reused,
     no more manual login needed.
"""
import base64
import os
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

UNSUBSCRIBE_FOOTER = (
    "\n\n---\n"
    "If this isn't relevant to you, just reply \"no thanks\" and I won't follow up again."
)


def _get_gmail_service():
    creds = None
    if os.path.exists(config.GMAIL_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(config.GMAIL_TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(config.GMAIL_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(config.GMAIL_TOKEN_FILE, "w") as token_file:
            token_file.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def send_email(to_address, subject, body, from_address=None):
    """Sends a real email. Returns the Gmail message ID on success."""
    service = _get_gmail_service()
    from_address = from_address or config.SENDER_EMAIL

    full_body = body.rstrip() + UNSUBSCRIBE_FOOTER
    message = MIMEText(full_body)
    message["to"] = to_address
    message["from"] = from_address
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return sent.get("id")