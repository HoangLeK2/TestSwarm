"""Organization member invitation: email + accept."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession

from core.env import device_farm_frontend_url, org_invite_expire_days
from db import crud as repo
from db.crud import organization_invite as invite_repo
from services.email_delivery import send_email
from services.email_templates import render_organization_invite_email

log = logging.getLogger(__name__)


def _invite_accept_url(token: str) -> str:
    base = device_farm_frontend_url().rstrip("/")
    return f"{base}/auth/accept-invite?token={quote(token)}"


def _build_invite_email(
    *,
    org_name: str,
    inviter_name: str | None,
    accept_url: str,
    existing_user: bool,
    recipient_email: str,
    expire_days: int,
) -> tuple[str, str, str]:
    inviter = (inviter_name or "").strip() or "Một thành viên trong nhóm"
    subject = f"{inviter} mời bạn tham gia {org_name}"
    text, html = render_organization_invite_email(
        inviter=inviter,
        org_name=org_name,
        accept_url=accept_url,
        existing_user=existing_user,
        recipient_email=recipient_email,
        expire_days=expire_days,
    )
    return subject, text, html


async def send_organization_invite_email(
    db: AsyncSession,
    *,
    invitation,
    org_name: str,
    inviter_name: str | None,
    existing_user: bool,
) -> bool:
    subject, text, html = _build_invite_email(
        org_name=org_name,
        inviter_name=inviter_name,
        accept_url=_invite_accept_url(invitation.token),
        existing_user=existing_user,
        recipient_email=invitation.email,
        expire_days=org_invite_expire_days(),
    )
    return await send_email(
        to=invitation.email,
        subject=subject,
        html_body=html,
        text_body=text,
    )


def invitation_is_expired(invitation) -> bool:
    expires = invitation.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= expires


async def accept_organization_invitation(
    db: AsyncSession,
    *,
    token: str,
    user,
) -> tuple[str, str]:
    """Accept invite for authenticated user. Returns (organization_id, org_name)."""
    invitation = await invite_repo.get_invitation_by_token(db, token)
    if invitation is None:
        raise ValueError("INVITE_NOT_FOUND")
    if invitation.status != "pending":
        raise ValueError("INVITE_NOT_PENDING")
    if invitation_is_expired(invitation):
        raise ValueError("INVITE_EXPIRED")

    user_email = (getattr(user, "email", None) or "").strip().lower()
    if user_email != (invitation.email or "").strip().lower():
        raise ValueError("INVITE_EMAIL_MISMATCH")

    org = await invite_repo.get_organization_by_id(db, invitation.organization_id)
    if org is None:
        raise ValueError("ORG_NOT_FOUND")
    if getattr(org, "status", "active") == "disabled":
        raise ValueError("ORG_DISABLED")

    if await invite_repo.user_has_membership(db, invitation.organization_id, user.id):
        await invite_repo.mark_invitation_accepted(db, invitation, user_id=user.id)
        return invitation.organization_id, org.business_name

    await repo.add_organization_member(
        db,
        organization_id=invitation.organization_id,
        user_id=user.id,
        role=invitation.role or "member",
    )
    try:
        if not user.default_org_id:
            user.default_org_id = invitation.organization_id
        await db.flush()
    except Exception:
        log.warning(
            "could not set active org after invite accept user_id=%s org_id=%s",
            user.id,
            invitation.organization_id,
        )
    await invite_repo.mark_invitation_accepted(db, invitation, user_id=user.id)
    return invitation.organization_id, org.business_name


async def create_and_email_invitation(
    db: AsyncSession,
    *,
    organization_id: str,
    email: str,
    role: str,
    invited_by_user_id: str,
    inviter_name: str | None,
) -> tuple[object, bool, bool]:
    """Returns (invitation, existing_user, email_sent)."""
    normalized = (email or "").strip().lower()
    target = await repo.get_user_by_email(db, normalized)
    existing_user = target is not None

    if existing_user:
        member = await repo.get_organization_member(db, organization_id, target.id)
        if member is not None:
            raise ValueError("ALREADY_MEMBER")

    org = await invite_repo.get_organization_by_id(db, organization_id)
    if org is None:
        raise ValueError("ORG_NOT_FOUND")

    invitation = await invite_repo.create_or_refresh_organization_invitation(
        db,
        organization_id=organization_id,
        email=normalized,
        role=role,
        invited_by_user_id=invited_by_user_id,
        expire_days=org_invite_expire_days(),
    )
    sent = await send_organization_invite_email(
        db,
        invitation=invitation,
        org_name=org.business_name,
        inviter_name=inviter_name,
        existing_user=existing_user,
    )
    if not sent:
        log.warning("invitation email not delivered to=%s org_id=%s", normalized, organization_id)
    return invitation, existing_user, sent
