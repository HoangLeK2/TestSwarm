"""services/webhook_dispatcher.py — Fire-and-forget async webhook dispatcher.

Usage:
    from services.webhook_dispatcher import dispatch_webhook
    await dispatch_webhook(org_id, "task.failed", {"execution_id": ..., ...})

Payload is HMAC-SHA256 signed with the org's webhook_secret.
Delivery is best-effort: failures are logged but not re-raised.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import socket
from urllib.parse import urlparse
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_TIMEOUT_SEC = 10


def _is_public_ip(ip: str) -> bool:
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


def _is_safe_webhook_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.hostname:
        return False
    hostname = parsed.hostname.strip().lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        return False

    try:
        addr_info = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        return False

    resolved_ips = {entry[4][0] for entry in addr_info if entry and entry[4]}
    if not resolved_ips:
        return False
    return all(_is_public_ip(ip) for ip in resolved_ips)


def _resolve_public_ips(hostname: str, port: int) -> set[str]:
    try:
        addr_info = socket.getaddrinfo(hostname, port)
    except socket.gaierror:
        return set()
    resolved_ips = {entry[4][0] for entry in addr_info if entry and entry[4]}
    public_ips = {ip for ip in resolved_ips if _is_public_ip(ip)}
    return public_ips if public_ips == resolved_ips else set()


async def dispatch_webhook(
    org_id: str,
    event: str,
    payload: Dict[str, Any],
) -> bool:
    """
    POST payload to the org's webhook URL if the event is subscribed.

    Returns True if delivered successfully, False otherwise.
    Swallows all exceptions — webhook failures must not affect the main flow.
    """
    try:
        return await _dispatch(org_id, event, payload)
    except Exception as exc:
        log.warning("webhook_dispatcher: unexpected error org=%s event=%s: %s", org_id, event, exc)
        return False


async def _dispatch(org_id: str, event: str, payload: Dict[str, Any]) -> bool:
    try:
        from db.database import activity_session
        from sqlalchemy import select
        from db.models.organization import Organization

        async with activity_session() as db:
            result = await db.execute(select(Organization).where(Organization.id == org_id))
            org = result.scalar_one_or_none()

        if org is None:
            return False

        webhook_url: Optional[str] = org.webhook_url
        if not webhook_url:
            return False  # not configured
        if not _is_safe_webhook_url(webhook_url):
            log.warning("webhook_dispatcher: blocked unsafe webhook url org=%s", org_id)
            return False
        parsed_webhook = urlparse(webhook_url)
        target_port = parsed_webhook.port or (443 if parsed_webhook.scheme == "https" else 80)
        initial_ips = _resolve_public_ips(parsed_webhook.hostname or "", target_port)
        if not initial_ips:
            log.warning("webhook_dispatcher: blocked webhook with unresolved/non-public host org=%s", org_id)
            return False

        # Check event subscription
        events = (org.webhook_events or "task.failed").split(",")
        events = [e.strip() for e in events]
        if event not in events and "*" not in events:
            log.debug("webhook_dispatcher: org=%s not subscribed to event=%s", org_id, event)
            return False

    except Exception as exc:
        log.warning("webhook_dispatcher: failed to fetch org config (org=%s): %s", org_id, exc)
        return False

    # Build body
    body_dict = {"event": event, **payload}
    body = json.dumps(body_dict, ensure_ascii=False, default=str)
    body_bytes = body.encode("utf-8")

    # HMAC signature
    headers = {"Content-Type": "application/json"}
    secret = org.webhook_secret
    if secret:
        sig = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
        headers["X-Webhook-Signature"] = f"sha256={sig}"

    # POST
    try:
        import httpx
        if parsed_webhook.hostname:
            # Re-resolve right before request to reduce DNS rebinding risk.
            latest_ips = _resolve_public_ips(parsed_webhook.hostname, target_port)
            if not latest_ips or latest_ips != initial_ips:
                log.warning(
                    "webhook_dispatcher: DNS changed or became unsafe org=%s host=%s",
                    org_id,
                    parsed_webhook.hostname,
                )
                return False
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.post(webhook_url, content=body_bytes, headers=headers)
            if resp.is_success:
                log.info("webhook_dispatcher: delivered event=%s org=%s status=%d", event, org_id, resp.status_code)
                return True
            else:
                log.warning(
                    "webhook_dispatcher: delivery failed event=%s org=%s status=%d body=%s",
                    event, org_id, resp.status_code, resp.text[:200],
                )
                return False
    except Exception as exc:
        log.warning("webhook_dispatcher: HTTP error event=%s org=%s: %s", event, org_id, exc)
        return False
