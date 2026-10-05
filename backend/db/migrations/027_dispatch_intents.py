"""027 — dispatch_intents table for execution idempotency.

Every dispatch path (scheduler fallback, campaign enqueue, Temporal trigger,
manual task submit) writes a row here first, keyed by a caller-supplied
`idempotency_key`. Duplicate submissions collide on the UNIQUE index and
return the existing row instead of double-firing.

Columns:
  id               UUID PK
  idempotency_key  TEXT UNIQUE — sha256 over (source, payload, iteration)
  source           TEXT — e.g. 'schedule:{id}', 'campaign:{id}:dev:{s}'
  payload_digest   TEXT — sha256 of the serialized payload (audit trail)
  status           TEXT — 'new' | 'accepted' | 'rejected' | 'failed'
  result_ref       TEXT — opaque pointer to the downstream runner (exec/wf id)
  created_at       TIMESTAMPTZ
  updated_at       TIMESTAMPTZ

Idempotent; safe to re-run.
"""
from __future__ import annotations


async def upgrade(conn) -> None:
    # gen_random_uuid() lives in pgcrypto on older Postgres (<13). Installing
    # the extension here — idempotent, no-op on clusters that already have it —
    # so a fresh database does not fail on first boot.
    await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dispatch_intents (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            idempotency_key TEXT NOT NULL,
            source          TEXT NOT NULL,
            payload_digest  TEXT,
            status          TEXT NOT NULL DEFAULT 'new',
            result_ref      TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    await conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_dispatch_intents_key
            ON dispatch_intents (idempotency_key);
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dispatch_intents_source
            ON dispatch_intents (source);
        """
    )
