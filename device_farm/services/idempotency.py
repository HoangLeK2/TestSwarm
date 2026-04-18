"""Execution idempotency contract.

Contract
--------
Every dispatch path produces an `idempotency_key` before enqueuing work.
The key is deterministic over (source, payload, iteration) so replay of
the same request — whether from a retried scheduler poll, a double-clicked
UI button, or a Temporal workflow restart — collapses into a single
execution.

Usage
-----
    key = make_idempotency_key(source="schedule:{id}:tick:{ts}", payload=cfg)
    intent = await claim_or_get_intent(key=key, source=..., payload=cfg)
    if intent.replay:
        return intent.result_ref  # work already scheduled elsewhere
    # …actually dispatch the work…
    await mark_intent_accepted(intent.id, result_ref=exec_id)

The UNIQUE index on `idempotency_key` makes the claim race-safe across
processes. `claim_or_get_intent` returns `replay=True` on collision.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text

from db.database import AsyncSessionLocal

log = logging.getLogger(__name__)


@dataclass
class DispatchIntent:
    id: str
    idempotency_key: str
    source: str
    payload_digest: str
    status: str
    result_ref: Optional[str]
    replay: bool


def _stable_json(payload: Any) -> str:
    try:
        return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    except Exception:
        return repr(payload)


def make_idempotency_key(source: str, payload: Any, *, salt: str = "") -> str:
    """Derive a deterministic 64-char hex key over source + payload + salt.

    `source` should embed iteration info (e.g. ``schedule:{id}:tick:{ts}``)
    so two distinct fires of the same schedule produce different keys.
    `salt` is available for tie-breakers (e.g. per-device in a fleet run).
    """
    digest = hashlib.sha256()
    digest.update(source.encode("utf-8"))
    digest.update(b"|")
    digest.update(_stable_json(payload).encode("utf-8"))
    if salt:
        digest.update(b"|")
        digest.update(salt.encode("utf-8"))
    return digest.hexdigest()


def payload_digest(payload: Any) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


async def claim_or_get_intent(
    *,
    key: str,
    source: str,
    payload: Any,
) -> DispatchIntent:
    """Insert a new intent row, or return the existing row if the key exists.

    Uses ``INSERT … ON CONFLICT (idempotency_key) DO NOTHING`` then a fallback
    SELECT. On conflict, `replay=True` — the caller SHOULD NOT enqueue work
    and should return the existing ``result_ref``.
    """
    digest = payload_digest(payload)
    async with AsyncSessionLocal() as db:
        insert = await db.execute(
            text(
                """
                INSERT INTO dispatch_intents
                    (idempotency_key, source, payload_digest, status)
                VALUES (:k, :s, :d, 'new')
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id::text, status, result_ref
                """
            ),
            {"k": key, "s": source, "d": digest},
        )
        row = insert.first()
        if row is not None:
            await db.commit()
            return DispatchIntent(
                id=row[0],
                idempotency_key=key,
                source=source,
                payload_digest=digest,
                status=row[1],
                result_ref=row[2],
                replay=False,
            )
        # Conflict path — read the existing row.
        existing = await db.execute(
            text(
                """
                SELECT id::text, source, payload_digest, status, result_ref
                FROM dispatch_intents
                WHERE idempotency_key = :k
                """
            ),
            {"k": key},
        )
        got = existing.first()
        if got is None:
            # Shouldn't happen — conflict without a visible row means we're
            # inside a concurrent deletion. Surface a clear error.
            await db.commit()
            raise RuntimeError(f"dispatch_intent missing after conflict: key={key}")
        await db.commit()
        return DispatchIntent(
            id=got[0],
            idempotency_key=key,
            source=got[1],
            payload_digest=got[2],
            status=got[3],
            result_ref=got[4],
            replay=True,
        )


async def mark_intent_status(
    intent_id: str,
    *,
    status: str,
    result_ref: Optional[str] = None,
) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                """
                UPDATE dispatch_intents
                SET status = :st,
                    result_ref = COALESCE(:rr, result_ref),
                    updated_at = NOW()
                WHERE id = :id
                """
            ),
            {"st": status, "rr": result_ref, "id": intent_id},
        )
        await db.commit()


async def mark_intent_accepted(intent_id: str, *, result_ref: str) -> None:
    await mark_intent_status(intent_id, status="accepted", result_ref=result_ref)


async def mark_intent_failed(intent_id: str, *, reason: str) -> None:
    await mark_intent_status(intent_id, status="failed", result_ref=reason[:512])
