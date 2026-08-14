"""Fast JSON helpers for internal payloads.

Public FastAPI request/response schemas stay on Pydantic. This module is for
internal cursors, JSON-RPC messages, trace payloads, and cache records where the
call sites already pass plain JSON-compatible dictionaries.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

try:
    import msgspec
except Exception:  # pragma: no cover - dependency is installed in production
    msgspec = None  # type: ignore[assignment]

try:
    import orjson
except Exception:  # pragma: no cover - dependency is installed in production
    orjson = None  # type: ignore[assignment]

_MSG_JSON_ENCODER = msgspec.json.Encoder() if msgspec is not None else None
_MSG_JSON_DECODER = msgspec.json.Decoder() if msgspec is not None else None
T = TypeVar("T")


def dumps_bytes(obj: Any) -> bytes:
    if _MSG_JSON_ENCODER is not None:
        try:
            return _MSG_JSON_ENCODER.encode(obj)
        except (TypeError, ValueError):
            pass
    if orjson is not None:
        try:
            return orjson.dumps(obj)
        except (TypeError, ValueError):
            pass
    return json.dumps(obj, separators=(",", ":"), default=str).encode("utf-8")


def dumps(obj: Any) -> str:
    return dumps_bytes(obj).decode("utf-8")


def loads(data: str | bytes | bytearray | memoryview) -> Any:
    if isinstance(data, memoryview):
        data = data.tobytes()
    if _MSG_JSON_DECODER is not None:
        try:
            return _MSG_JSON_DECODER.decode(data)
        except Exception:
            pass
    if orjson is not None:
        try:
            return orjson.loads(data)
        except Exception:
            pass
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    return json.loads(data)


def decode_as(data: str | bytes | bytearray | memoryview, typ: type[T]) -> T:
    if isinstance(data, memoryview):
        data = data.tobytes()
    if msgspec is not None:
        try:
            return msgspec.json.decode(data, type=typ)
        except Exception:
            pass
    value = loads(data)
    if isinstance(value, typ):
        return value
    raise TypeError(f"decoded JSON is not {typ!r}")
