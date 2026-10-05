"""Jinja2 HTML/text email templates (aligned with dashboard auth UI tokens)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    auto_reload=False,
)


def render_organization_invite_email(
    *,
    inviter: str,
    org_name: str,
    accept_url: str,
    existing_user: bool,
    recipient_email: str,
    expire_days: int,
) -> tuple[str, str]:
    """Return (plain_text, html) for an organization member invitation."""
    context = {
        "inviter": inviter,
        "org_name": org_name,
        "accept_url": accept_url,
        "existing_user": existing_user,
        "recipient_email": recipient_email,
        "expire_days": expire_days,
        "year": datetime.now(timezone.utc).year,
    }
    text = _env.get_template("organization_invite.txt.jinja").render(**context)
    html = _env.get_template("organization_invite.html.jinja").render(**context)
    return text.strip(), html.strip()
