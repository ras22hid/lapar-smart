import os
import smtplib
import warnings
from email.mime.text import MIMEText
from email.utils import formataddr


def send_password_reset_email(to_email, admin_id, reset_url):
    """Sends the password reset link over Gmail SMTP (smtp.gmail.com:587,
    STARTTLS) using an account + App Password configured via env vars.
    Returns True on success, False otherwise -- callers should treat a
    False return as non-fatal (the request should not 500 just because
    an email couldn't be sent) but should log it."""
    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if gmail_address:
        # Defensive: a stray leading BOM (﻿) from how the env var was set
        # (seen previously with TURSO_DATABASE_URL/TURSO_AUTH_TOKEN, see
        # db.py) breaks smtplib's ascii-only SMTP command encoding.
        gmail_address = gmail_address.strip().lstrip("﻿")
    if gmail_app_password:
        gmail_app_password = gmail_app_password.strip().lstrip("﻿")
    if not gmail_address or not gmail_app_password:
        warnings.warn(
            "GMAIL_ADDRESS / GMAIL_APP_PASSWORD are not set: password reset "
            "emails cannot be sent.",
            RuntimeWarning,
        )
        return False

    body = (
        f"Hi {admin_id},\n\n"
        "We received a request to reset your Lapar Smart Cafe Admin password.\n\n"
        f"Reset it here (this link expires in 30 minutes):\n{reset_url}\n\n"
        "If you didn't request this, you can safely ignore this email.\n\n"
        "-- Lapar Smart · Lazaria Cafe"
    )
    msg = MIMEText(body)
    msg["Subject"] = "Reset your Lapar Smart Cafe Admin password"
    # Display name only -- the underlying address is still gmail_address
    # (Gmail's SMTP rejects a From that doesn't match the authenticated
    # account/alias), but this is what recipients see in their inbox
    # unless they open full headers.
    msg["From"] = formataddr(("Lazaria Cafe", gmail_address))
    msg["To"] = to_email

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as server:
            server.starttls()
            server.login(gmail_address, gmail_app_password)
            server.sendmail(gmail_address, [to_email], msg.as_string())
        return True
    except Exception as exc:
        warnings.warn(f"Failed to send password reset email: {exc}", RuntimeWarning)
        return False
