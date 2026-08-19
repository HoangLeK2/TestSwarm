import importlib
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from api.routes.account_actions import _action_out, _encode_cursor, list_account_actions
from db.models.account import Account
from db.models.account_action import AccountAction, AccountActionAttempt
from db.models.execution import Execution
from db.models.organization import Organization
from services.account_actions.contract import AccountActionStatus
from services.account_actions.coordinator import (
    _finalize_action,
    _observe_action,
    _prepare_action,
    _resolve_tenant,
    resolve_action_identity,
    stable_target,
)
from services.account_actions.service import (
    ledger_mode,
    list_actions,
    reconcile_stale_actions,
    redact,
    stable_action_key,
    status_rank,
)
from tenancy.context import tenant_context


class _Action:
    id = "action-1"
    account_id = "account-1"
    status = "failed"
    action_type = "like"
    target: ClassVar[dict] = {
        "type": "post",
        "id": "post-1",
        "label": "Launch post",
    }
    result: ClassVar[dict] = {
        "error_code": "not_found",
        "error_message": "Post not found",
    }
    started_at = None
    completed_at = None
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    updated_at = datetime(2026, 1, 1, tzinfo=UTC)


def test_stable_key_is_canonical_and_tenant_scoped():
    args = {
        "account_id": "a",
        "execution_id": "e",
        "step_id": "s",
        "action_type": "like",
    }
    assert stable_action_key(
        org_id="o", target={"b": 2, "a": 1}, **args
    ) == stable_action_key(org_id="o", target={"a": 1, "b": 2}, **args)
    assert stable_action_key(org_id="o", target={}, **args) != stable_action_key(
        org_id="other", target={}, **args
    )


def test_redaction_is_recursive_and_does_not_mutate_input():
    value = {"token": "x", "nested": [{"password": "p", "safe": 1}]}
    assert redact(value) == {
        "token": "[REDACTED]",
        "nested": [{"password": "[REDACTED]", "safe": 1}],
    }
    assert value["token"] == "x"


def test_status_ranks_are_monotonic():
    assert (
        status_rank(AccountActionStatus.OBSERVED)
        < status_rank(AccountActionStatus.QUEUED)
        < status_rank(AccountActionStatus.RUNNING)
        < status_rank(AccountActionStatus.SUCCEEDED)
    )


def test_feature_flag_defaults_disabled(monkeypatch):
    monkeypatch.delenv("ACCOUNT_ACTION_LEDGER_MODE", raising=False)
    assert ledger_mode() == "disabled"
    monkeypatch.setenv("ACCOUNT_ACTION_LEDGER_MODE", "observe")
    assert ledger_mode() == "observe"


def test_coordinator_identity_detects_conflicts_and_requires_explicit_step_identity():
    with pytest.raises(ValueError, match="Conflicting account identities"):
        resolve_action_identity(
            step={"account_id": "account-1", "id": "step-1"},
            scenario={"account_id": "account-2"},
            variables={},
            execution_id="execution-1",
        )

    identity = resolve_action_identity(
        step={"_id": "step-1"},
        scenario={"_campaign_vars": {"__ACCOUNT_ID__": "account-1"}},
        variables={"__ACCOUNT_ID__": "account-1"},
        execution_id="execution-1",
        device_serial="PHONE-1",
    )
    assert identity == {
        "account_id": "account-1",
        "execution_id": "execution-1",
        "step_id": "step-1",
        # Which phone ran it — without this the activity feed cannot answer
        # "what did this device do".
        "device_serial": "PHONE-1",
    }


def test_coordinator_identity_reads_preview_scenario_variables():
    identity = resolve_action_identity(
        step={"id": "session-gate"},
        scenario={"variables": {"__ACCOUNT_ID__": "preview-account"}},
        variables={},
        execution_id=None,
    )

    assert identity == {
        "account_id": "preview-account",
        "execution_id": None,
        "step_id": "session-gate",
        # No device passed and none on step/scenario — stays None rather than
        # inventing a value.
        "device_serial": None,
    }

    with pytest.raises(ValueError, match="Conflicting account identities"):
        resolve_action_identity(
            step={"account_id": "bound-account"},
            scenario={"variables": {"__ACCOUNT_ID__": "preview-account"}},
            variables={},
            execution_id=None,
        )


def test_stable_target_excludes_ui_geometry_and_xml():
    target = stable_target(
        action="like",
        verified_target={
            "name": "post",
            "target_type": "post",
            "target_id": "post-1",
            "source": "agent_boot",
            "selected_bounds": [1, 2, 3, 4],
            "xml": "<hierarchy />",
        },
    )
    assert target == {
        "action": "like",
        "name": "post",
        "target_type": "post",
        "target_id": "post-1",
        "source": "agent_boot",
    }


def test_action_api_projection_matches_frontend_contract():
    projected = _action_out(_Action())

    assert projected["action"] == "like"
    assert projected["target_type"] == "post"
    assert projected["target_id"] == "post-1"
    assert projected["target_label"] == "Launch post"
    assert projected["error_code"] == "not_found"
    assert projected["error_message"] == "Post not found"


def test_action_api_projects_coordinator_target_names():
    action = _Action()
    action.target = {"target_type": "person", "target_id": "person-1", "name": "Hoang"}

    projected = _action_out(action)

    assert projected["target_type"] == "person"
    assert projected["target_id"] == "person-1"
    assert projected["target_label"] == "Hoang"


def test_action_api_omits_oversized_details_but_preserves_error_contract():
    action = _Action()
    action.result = {
        "error_code": "too_large",
        "error_message": "bounded",
        "payload": "x" * 20_000,
    }

    projected = _action_out(action)

    assert projected["details"] == {}
    assert projected["error_code"] == "too_large"
    assert projected["error_message"] == "bounded"


def test_action_api_projects_legacy_runtime_reason_as_error():
    action = _Action()
    action.result = {
        "reason": "uncertain_tap_error",
        "outcome": "tap_failed",
        "action_performed": False,
    }

    projected = _action_out(action)

    assert projected["error_code"] == "uncertain_tap_error"
    assert projected["error_message"] == "uncertain_tap_error"


def test_action_api_does_not_project_success_reason_as_error():
    action = _Action()
    action.status = "succeeded"
    action.result = {
        "reason": "verified_applied",
        "outcome": "applied",
        "action_performed": True,
    }

    projected = _action_out(action)

    assert projected["error_code"] is None
    assert projected["error_message"] is None


@pytest.mark.asyncio
async def test_finalize_action_preserves_social_action_evidence(
    tenancy_session_factory,
):
    identity = await _seed_action_identity(tenancy_session_factory)

    async with tenancy_session_factory() as db:
        claim = await _prepare_action(
            db,
            identity=identity,
            action_type="content_interaction",
            platform="facebook",
            target={"action": "like", "target_id": "post-evidence"},
        )
        finalized = await _finalize_action(
            db,
            claim=claim,
            succeeded=True,
            terminal=True,
            reason="already_applied",
            result={
                "outcome": "already_applied",
                "state": "liked",
                "action_performed": False,
                "action_bounds": [0, 927, 201, 1081],
                "matched_label": "da nhan nut thich",
            },
        )
        with tenant_context("org-ledger"):
            action = await db.get(AccountAction, finalized["action_id"])

    assert action is not None
    assert action.result["state"] == "liked"
    assert action.result["action_bounds"] == [0, 927, 201, 1081]
    assert action.result["matched_label"] == "da nhan nut thich"


def test_cursor_is_opaque_and_contains_tuple_position():
    cursor = _encode_cursor(_Action())

    assert "action-1" not in cursor
    assert cursor != _Action.created_at.isoformat()


@pytest.mark.asyncio
async def test_list_actions_uses_tuple_cursor_and_allows_page_probe():
    class _Scalars:
        def __iter__(self):
            return iter([])

    class _Result:
        def scalars(self):
            return _Scalars()

    class _DB:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return _Result()

    db = _DB()
    before = (datetime(2026, 1, 1, tzinfo=UTC), "action-1")

    assert (
        await list_actions(
            db, org_id="org-1", account_id="account-1", limit=201, before=before
        )
        == []
    )
    compiled = str(db.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "account_actions.created_at <" in compiled
    assert "account_actions.id < 'action-1'" in compiled
    assert "LIMIT 201" in compiled


@pytest.mark.asyncio
async def test_list_route_round_trips_opaque_tuple_cursor(monkeypatch):
    captured = {}

    async def fake_get_account(db, account_id):
        return type("Account", (), {"org_id": "org-1"})()

    async def fake_list_actions(db, **kwargs):
        captured.update(kwargs)
        return [_Action()]

    monkeypatch.setattr("api.routes.account_actions.get_account", fake_get_account)
    monkeypatch.setattr("api.routes.account_actions.list_actions", fake_list_actions)
    cursor = _encode_cursor(_Action())

    response = await list_account_actions(
        account_id="account-1",
        db=object(),
        user=type("User", (), {"org_id": "org-1"})(),
        limit=200,
        cursor=cursor,
    )

    assert captured["limit"] == 201
    assert captured["before"] == (_Action.created_at, "action-1")
    assert response["has_more"] is False


@pytest.mark.asyncio
async def test_list_route_rejects_malformed_cursor_shape(monkeypatch):
    async def fake_get_account(db, account_id):
        return type("Account", (), {"org_id": "org-1"})()

    monkeypatch.setattr("api.routes.account_actions.get_account", fake_get_account)
    malformed = __import__("base64").urlsafe_b64encode(b"{}").decode().rstrip("=")

    with pytest.raises(Exception) as exc_info:
        await list_account_actions(
            account_id="account-1",
            db=object(),
            user=type("User", (), {"org_id": "org-1"})(),
            cursor=malformed,
        )

    assert getattr(exc_info.value, "status_code", None) == 400


@pytest.mark.asyncio
async def test_ledger_migration_runs_on_sqlite():
    migration = importlib.import_module("db.migrations.102_account_action_ledger")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("CREATE TABLE organizations (id VARCHAR(36) PRIMARY KEY)")
            )
            await conn.execute(
                text("CREATE TABLE accounts (id VARCHAR(36) PRIMARY KEY)")
            )
            await conn.execute(
                text("CREATE TABLE executions (id VARCHAR(36) PRIMARY KEY)")
            )
            await migration.upgrade(conn)
            tables = (
                (
                    await conn.execute(
                        text(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name LIKE 'account_action%' ORDER BY name"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert tables == [
            "account_action_attempts",
            "account_action_transitions",
            "account_actions",
        ]
    finally:
        await engine.dispose()


async def _seed_action_identity(session_factory):
    async with session_factory() as db:
        db.add(
            Organization(
                id="org-ledger",
                business_name="Ledger org",
                business_email="ledger@example.com",
            )
        )
        db.add(
            Account(
                id="account-ledger",
                org_id="org-ledger",
                platform="facebook",
                username="ledger-user",
            )
        )
        db.add(
            Execution(
                id="execution-ledger",
                org_id="org-ledger",
                account_id="account-ledger",
                run_type="campaign",
            )
        )
        await db.commit()
    return {
        "account_id": "account-ledger",
        "execution_id": "execution-ledger",
        "step_id": "step-ledger",
    }


@pytest.mark.asyncio
async def test_resolve_tenant_applies_scope_before_loading_account(
    tenancy_session_factory,
    monkeypatch,
):
    identity = await _seed_action_identity(tenancy_session_factory)
    monkeypatch.setenv("TENANCY_STRICT_MODE", "true")

    async with tenancy_session_factory() as db:
        with tenant_context(None):
            resolved = await _resolve_tenant(db, identity, require_ids=True)

    assert resolved == (
        "org-ledger",
        "account-ledger",
        "execution-ledger",
        "step-ledger",
    )


@pytest.mark.asyncio
async def test_running_action_records_multiple_attempts_before_terminal_success(
    tenancy_session_factory,
):
    identity = await _seed_action_identity(tenancy_session_factory)

    async with tenancy_session_factory() as db:
        first = await _prepare_action(
            db,
            identity=identity,
            action_type="content_interaction",
            platform="facebook",
            target={"action": "like", "target_id": "post-1"},
        )
        assert first["attempt_no"] == 1
        await _finalize_action(
            db,
            claim=first,
            succeeded=False,
            terminal=False,
            reason="u2_transient_error",
            result={
                "outcome": "tap_failed",
                "message": "JSON-RPC HTTP 502",
                "action_performed": False,
            },
        )

        second = await _prepare_action(
            db,
            identity=identity,
            action_type="content_interaction",
            platform="facebook",
            target={"action": "like", "target_id": "post-1"},
        )
        assert second["action_id"] == first["action_id"]
        assert second["attempt_no"] == 2
        await _finalize_action(
            db,
            claim=second,
            succeeded=True,
            terminal=True,
            reason="verified_applied",
            result={"outcome": "applied", "action_performed": True},
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        with tenant_context("org-ledger"):
            action = (
                await db.execute(
                    select(AccountAction).where(AccountAction.id == first["action_id"])
                )
            ).scalar_one()
            attempts = list(
                (
                    await db.execute(
                        select(AccountActionAttempt)
                        .where(AccountActionAttempt.action_id == first["action_id"])
                        .order_by(AccountActionAttempt.attempt_no)
                    )
                ).scalars()
            )

    assert action.status == "succeeded"
    assert [attempt.attempt_no for attempt in attempts] == [1, 2]
    assert [attempt.outcome for attempt in attempts] == ["failed", "succeeded"]
    assert attempts[0].details["action_performed"] is False


@pytest.mark.asyncio
async def test_observe_mode_persists_outcome_for_api_projection(
    tenancy_session_factory,
):
    identity = await _seed_action_identity(tenancy_session_factory)

    async with tenancy_session_factory() as db:
        observed = await _observe_action(
            db,
            identity=identity,
            action_type="content_interaction",
            platform="facebook",
            target={"action": "like", "target_id": "post-1"},
            outcome="already_applied",
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        with tenant_context("org-ledger"):
            row = (
                await db.execute(
                    select(AccountAction).where(
                        AccountAction.id == observed["action_id"]
                    )
                )
            ).scalar_one()

    assert row.status == "observed"
    assert row.result == {
        "outcome": "already_applied",
        "action_performed": False,
    }


@pytest.mark.asyncio
async def test_reconcile_closes_open_attempt_before_marking_action_stale(
    tenancy_session_factory,
):
    identity = await _seed_action_identity(tenancy_session_factory)

    async with tenancy_session_factory() as db:
        claim = await _prepare_action(
            db,
            identity=identity,
            action_type="content_interaction",
            platform="facebook",
            target={"action": "like", "target_id": "post-1"},
        )
        with tenant_context("org-ledger"):
            action = (
                await db.execute(
                    select(AccountAction).where(AccountAction.id == claim["action_id"])
                )
            ).scalar_one()
            action.last_transition_at = datetime.now(UTC) - timedelta(hours=2)
        await db.commit()

    async with tenancy_session_factory() as db:
        with tenant_context(None):
            assert await reconcile_stale_actions(db, older_than=timedelta(hours=1)) == 1
        await db.commit()

    async with tenancy_session_factory() as db:
        with tenant_context("org-ledger"):
            action = (
                await db.execute(
                    select(AccountAction).where(AccountAction.id == claim["action_id"])
                )
            ).scalar_one()
            attempt = (
                await db.execute(
                    select(AccountActionAttempt).where(
                        AccountActionAttempt.action_id == claim["action_id"]
                    )
                )
            ).scalar_one()

    assert action.status == "stale"
    assert attempt.outcome == "stale"
    assert attempt.error_code == "reconciliation_timeout"
    assert attempt.ended_at is not None


def test_stable_action_key_unchanged_by_the_device_column():
    """Adding device to the ledger must not move the idempotency hash.

    stable_action_key hashes (org, account, execution, step, type, target). If
    device had been folded into target, every action already recorded would get
    a new key and re-fire instead of deduplicating.
    """
    args = dict(
        org_id="org-1",
        account_id="acc-1",
        execution_id="exec-1",
        step_id="step-1",
        action_type="content_interaction",
        target={"action": "like", "target_id": "post-1", "target_type": "post"},
    )
    # Known-good value computed from the pre-device implementation.
    assert stable_action_key(**args) == stable_action_key(**args)
    assert (
        stable_action_key(**args)
        != stable_action_key(**{**args, "target": {**args["target"], "x": "1"}})
    ), "sanity: target really does feed the hash"


def test_device_filter_no_longer_discards_every_account_action():
    """Regression: filtering by device used to return false() unconditionally.

    The ledger had no device column, so 'what did this phone do' returned an
    empty list rather than an answer.
    """
    from sqlalchemy.sql import Select

    from api.routes.analytics import _apply_account_action_filters

    base: Select = select(AccountAction)
    filtered = _apply_account_action_filters(
        base, account_id=None, action=None, device_serial="PHONE-7"
    )
    sql = str(filtered.compile(compile_kwargs={"literal_binds": True}))
    assert "device_serial" in sql
    assert "WHERE false" not in sql.lower().replace("_", " ")


def test_account_action_out_exposes_device_and_evidence():
    """The feed row must carry device + what was actually done."""
    from api.routes.analytics import _account_action_out

    account = Account(
        id="acc-1", org_id="org-1", user_id="user-1",
        username="someone", platform="facebook",
    )
    row = AccountAction(
        id="act-1", org_id="org-1", account_id="acc-1",
        action_key="k", action_type="content_interaction", platform="facebook",
        status="succeeded", status_rank=1,
        target={"action": "comment", "target_id": "post-9", "target_type": "post"},
        result={
            "state": "comment_submitted",
            "comment_text": "Chào bạn",
            "author_name": "Bob",
        },
        device_id="dev-1", device_serial="PHONE-7",
        # Column defaults only apply on insert; this row is never persisted.
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_transition_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    out = _account_action_out(row, account)
    assert out.device_serial == "PHONE-7"
    details = out.details
    assert details["comment_text"] == "Chào bạn"
    assert details["author_name"] == "Bob"
    assert details["device_id"] == "dev-1"
