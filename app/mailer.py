import os
import smtplib
import warnings
from email.mime.text import MIMEText
from email.utils import formataddr

from .db import clean_env_value


def _send_gmail(to_email, subject, body, purpose):
    """Sends one plain-text email over Gmail SMTP (smtp.gmail.com:587,
    STARTTLS) using an account + App Password configured via env vars.
    Returns True on success, False otherwise -- callers should treat a
    False return as non-fatal (the request should not 500 just because
    an email couldn't be sent) but should log it."""
    gmail_address = clean_env_value(os.environ.get("GMAIL_ADDRESS"))
    gmail_app_password = clean_env_value(os.environ.get("GMAIL_APP_PASSWORD"))
    if not gmail_address or not gmail_app_password:
        warnings.warn(
            f"GMAIL_ADDRESS / GMAIL_APP_PASSWORD are not set: {purpose} "
            "emails cannot be sent.",
            RuntimeWarning,
        )
        return False

    msg = MIMEText(body)
    msg["Subject"] = subject
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
        warnings.warn(f"Failed to send {purpose} email: {exc}", RuntimeWarning)
        return False


def send_password_reset_email(to_email, admin_id, reset_url):
    body = (
        f"Hi {admin_id},\n\n"
        "We received a request to reset your Lapar Smart Cafe Admin password.\n\n"
        f"Reset it here (this link expires in 30 minutes):\n{reset_url}\n\n"
        "If you didn't request this, you can safely ignore this email.\n\n"
        "-- Lapar Smart · Lazaria Cafe"
    )
    return _send_gmail(
        to_email, "Reset your Lapar Smart Cafe Admin password", body, "password reset"
    )


def ready_message(order):
    """The order-ready alert text, shared by the on-page banner and the
    email. A meeting-room order is delivered by cafe staff; a counter order
    is collected and paid for at the counter."""
    if order["order_type"] == "MeetingRoom":
        return (
            f"Your catering order is ready. Cafe staff will deliver it to "
            f"{order['meeting_room']}."
        )
    return "Your order is ready for collection and payment at the counter!"


def send_order_ready_email(order):
    """Order-status alert over Gmail, sent when the cafe marks the order
    Ready. `order` is an orders row. Returns False (non-fatal) when the
    order has no email address or the email could not be sent."""
    to_email = (order["email"] or "").strip()
    if not to_email:
        return False
    name = order["staff_name"] or order["staff_id"]
    lines = [f"Hi {name},", "", ready_message(order), "", f"Order #{order['order_id']}"]
    if order["order_type"] == "MeetingRoom":
        lines += [
            f"Package: {order['package_name']} x {order['package_qty']}",
            f"Meeting room: {order['meeting_room']}",
            f"Requested time: {order['meeting_time']}",
        ]
    lines += [f"Total: RM {order['total_amount']:.2f}", "", "-- Lapar Smart · Lazaria Cafe"]
    return _send_gmail(
        to_email,
        f"Your Lapar Smart order #{order['order_id']} is ready",
        "\n".join(lines),
        "order ready",
    )
