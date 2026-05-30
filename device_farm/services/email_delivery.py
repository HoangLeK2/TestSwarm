"""SMTP email delivery via aiosmtplib (stdlib email.message)."""
from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from core.env import (
    smtp_from_address,
    smtp_host,
    smtp_password,
    smtp_port,
    smtp_use_ssl,
    smtp_use_tls,
    smtp_user,
)

log = logging.getLogger(__name__)


def smtp_configured() -> bool:
    return bool(smtp_host())


async def send_email(
    *,
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> bool:
    """Send an email. Returns True on success. Logs invite URL when SMTP is off."""
    recipient = (to or "").strip()
    if not recipient:
        return False

    if not smtp_configured():
        log.info(
            "email skipped (SMTP not configured) to=%s subject=%s link_hint=%s",
            recipient,
            subject,
            (text_body or html_body)[:500],
        )
        return False

    message = EmailMessage()
    message["From"] = smtp_from_address()
    message["To"] = recipient
    message["Subject"] = subject
    plain = text_body or _html_to_plain(html_body)
    message.set_content(plain)
    message.add_alternative(html_body, subtype="html")

    try:
        if smtp_use_ssl():
            await aiosmtplib.send(
                message,
                hostname=smtp_host(),
                port=smtp_port(),
                username=smtp_user() or None,
                password=smtp_password() or None,
                use_tls=True,
            )
        else:
            await aiosmtplib.send(
                message,
                hostname=smtp_host(),
                port=smtp_port(),
                username=smtp_user() or None,
                password=smtp_password() or None,
                start_tls=smtp_use_tls(),
            )
        return True
    except Exception:
        log.exception("failed to send email to=%s subject=%s", recipient, subject)
        return False


def _html_to_plain(html: str) -> str:
    text = html.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    for tag in ("<p>", "</p>", "<strong>", "</strong>", "<a>", "</a>"):
        text = text.replace(tag, "")
    return text.strip()
