import asyncio
from contextlib import asynccontextmanager

import pytest

from services.account_actions import reconcile_worker


class _Bind:
    class dialect:
        name = "sqlite"


class _Session:
    began = False

    def get_bind(self):
        return _Bind()

    @asynccontextmanager
    async def begin(self):
        self.began = True
        try:
            yield
        finally:
            self.began = False


class _SessionContext:
    async def __aenter__(self):
        self.session = _Session()
        return self.session

    async def __aexit__(self, *_args):
        return None


def test_reconcile_config_defaults_and_bounds(monkeypatch):
    monkeypatch.setenv("ACCOUNT_ACTION_RECONCILE_INTERVAL_SECONDS", "1")
    monkeypatch.setenv("ACCOUNT_ACTION_RECONCILE_STALE_AFTER_SECONDS", "99999999")
    assert reconcile_worker.reconcile_interval_seconds() == 5
    assert reconcile_worker.reconcile_stale_after_seconds() == 2592000

    monkeypatch.setenv("ACCOUNT_ACTION_RECONCILE_INTERVAL_SECONDS", "invalid")
    assert reconcile_worker.reconcile_interval_seconds() == 60


@pytest.mark.asyncio
async def test_reconcile_skips_database_when_ledger_disabled(monkeypatch):
    monkeypatch.setattr(reconcile_worker, "ledger_mode", lambda: "disabled")
    monkeypatch.setattr(
        reconcile_worker,
        "AsyncSessionLocal",
        lambda: pytest.fail("database should not be opened"),
    )
    assert await reconcile_worker.run_account_action_reconcile_once() == 0


@pytest.mark.asyncio
async def test_reconcile_runs_in_session_transaction(monkeypatch):
    observed = {}

    async def _reconcile(db, *, older_than):
        observed["db"] = db
        observed["seconds"] = older_than.total_seconds()
        return 3

    monkeypatch.setattr(reconcile_worker, "ledger_mode", lambda: "observe")
    monkeypatch.setattr(reconcile_worker, "AsyncSessionLocal", _SessionContext)
    monkeypatch.setattr(reconcile_worker, "reconcile_stale_actions", _reconcile)
    monkeypatch.setenv("ACCOUNT_ACTION_RECONCILE_STALE_AFTER_SECONDS", "120")

    assert await reconcile_worker.run_account_action_reconcile_once() == 3
    assert isinstance(observed["db"], _Session)
    assert observed["seconds"] == 120


@pytest.mark.asyncio
async def test_reconcile_acquires_lock_inside_transaction(monkeypatch):
    observed = {}

    async def _lock(db):
        observed["lock_inside_transaction"] = db.began
        return True

    async def _unlock(_db):
        return None

    async def _reconcile(_db, *, older_than):
        del older_than
        return 0

    monkeypatch.setattr(reconcile_worker, "ledger_mode", lambda: "enabled")
    monkeypatch.setattr(reconcile_worker, "AsyncSessionLocal", _SessionContext)
    monkeypatch.setattr(reconcile_worker, "_try_advisory_lock", _lock)
    monkeypatch.setattr(reconcile_worker, "_advisory_unlock", _unlock)
    monkeypatch.setattr(reconcile_worker, "reconcile_stale_actions", _reconcile)

    await reconcile_worker.run_account_action_reconcile_once()

    assert observed["lock_inside_transaction"] is True


@pytest.mark.asyncio
async def test_loop_propagates_cancellation(monkeypatch):
    async def _cancel():
        raise asyncio.CancelledError

    monkeypatch.setattr(reconcile_worker, "run_account_action_reconcile_once", _cancel)
    with pytest.raises(asyncio.CancelledError):
        await reconcile_worker.account_action_reconcile_loop(interval_seconds=5)


@pytest.mark.asyncio
async def test_reconcile_waits_for_unlock_when_cancelled(monkeypatch):
    unlocked = asyncio.Event()

    async def _reconcile(_db, *, older_than):
        del older_than
        raise asyncio.CancelledError

    async def _unlock(_db):
        await asyncio.sleep(0)
        unlocked.set()

    monkeypatch.setattr(reconcile_worker, "ledger_mode", lambda: "enabled")
    monkeypatch.setattr(reconcile_worker, "AsyncSessionLocal", _SessionContext)
    monkeypatch.setattr(reconcile_worker, "reconcile_stale_actions", _reconcile)
    monkeypatch.setattr(reconcile_worker, "_advisory_unlock", _unlock)

    with pytest.raises(asyncio.CancelledError):
        await reconcile_worker.run_account_action_reconcile_once()
    assert unlocked.is_set()
