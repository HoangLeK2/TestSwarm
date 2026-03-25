from __future__ import annotations

import secrets
from datetime import datetime, timezone
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid4())


def _api_key() -> str:
    return secrets.token_urlsafe(32)

