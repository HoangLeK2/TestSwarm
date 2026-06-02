"""Artifact signed URL service (DF-T-06-012)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 3600
_MAX_TTL_SECONDS = 86400


def presigned_artifact_url(
    object_key: str,
    *,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    content_type: str = "image/jpeg",
) -> dict[str, Any]:
    """Generate signed URL for artifact object_key."""
    from services import minio_store

    ttl = min(max(60, ttl_seconds), _MAX_TTL_SECONDS)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)

    if not minio_store.enabled():
        return {
            "url": None,
            "expires_at": expires_at.isoformat(),
            "content_type": content_type,
            "proxy_required": True,
        }

    url = minio_store.presigned_get(object_key, expires_seconds=ttl)
    return {
        "url": url,
        "expires_at": expires_at.isoformat(),
        "content_type": content_type,
        "proxy_required": False,
    }
