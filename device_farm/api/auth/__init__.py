"""Unified auth primitives for device-farm API.

Exports:
    AuthContext — authenticated subject carried into a request.
    decode_access_token — single JWT parse path used by HTTP + WS.
    policy — ownership/authorization checks scoped to a caller.
"""
from __future__ import annotations

from .context import (
    AuthContext,
    decode_access_token,
    decode_access_token_async,
    try_decode_access_token,
)
from . import policy

__all__ = [
    "AuthContext",
    "decode_access_token",
    "decode_access_token_async",
    "try_decode_access_token",
    "policy",
]
