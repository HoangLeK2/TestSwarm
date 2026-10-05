from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from typing import Any


def account_metadata_value(metadata: Any, *keys: str) -> str:
    if not isinstance(metadata, dict):
        return ""
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def generate_totp(secret: str, *, now: int | None = None, digits: int = 6, period: int = 30) -> str:
    normalized = "".join(str(secret or "").split()).upper()
    if not normalized:
        return ""
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    key = base64.b32decode(normalized + padding, casefold=True)
    counter = int((now if now is not None else time.time()) // period)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)
