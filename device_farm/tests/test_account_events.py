"""Tests for account_events CRUD and recorder."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from db.crud.account_event import (
    decode_event_cursor,
    encode_event_cursor,
    insert_events_batch,
    list_account_events,
)
from services.account_event_recorder import AccountEventRecorder, reset_account_event_recorder


def test_event_cursor_roundtrip():
    now = datetime.now(timezone.utc)
    cur = encode_event_cursor(now, "abc-123")
    t, eid = decode_event_cursor(cur)
    assert eid == "abc-123"
    assert t.replace(microsecond=0) == now.replace(microsecond=0)


def test_recorder_redacts_secrets():
    rec = AccountEventRecorder(enabled=True, max_pending=10)
    rec.record(
        account_id="a1",
        event_type="account.updated",
        details={"password": "secret", "notes": "ok"},
    )
    assert rec._pending[0].details == {"notes": "ok"}


def test_recorder_drops_when_full():
    rec = AccountEventRecorder(enabled=True, max_pending=2)
    rec.record(account_id="a1", event_type="account.created")
    rec.record(account_id="a2", event_type="account.created")
    rec.record(account_id="a3", event_type="account.created")
    assert rec.dropped_total == 1
    assert len(rec._pending) == 2


def test_list_account_events_importable():
    assert callable(insert_events_batch)
    assert callable(list_account_events)
    reset_account_event_recorder()
