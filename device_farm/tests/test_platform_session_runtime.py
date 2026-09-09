from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.database import Base
from common.variable_resolver import VariableContext
from db.models.account import Account
from db.models.device import Device
from db.models.enums import DevicePlatformSessionState
from services.campaign.account_resolver import ResolvedDeviceAccount
from services.campaign.dispatcher import _apply_platform_session_guard_to_accounts
from services.device_platform_session import get_platform_session, mark_active
from services.platform_readiness import PlatformReadinessResult, PlatformReadinessStatus
from services.facebook_session_guard import (
    FacebookSessionGuardDecision,
    FacebookSessionGuardMode,
    FacebookSessionGuardOutcome,
)
from services.platform_session_runtime import (
    _resolve_runtime_target,
    apply_platform_session_gate,
    guard_reason_allows_login_recovery,
    platform_session_requirement_platforms,
    scenario_registry_has_platform_login_gate,
    scenario_registry_platform_session_requirements,
)
from tenancy.context import tenant_context, use_tenant_scope
from tasks.scenario.steps.platform_session import handle_platform_session_gate


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


def _readiness(status: PlatformReadinessStatus) -> PlatformReadinessResult:
    return PlatformReadinessResult(
        status=status,
        reason=f"test_{status.value}",
        attempted_at=datetime.now(timezone.utc),
        app_package="com.facebook.katana",
    )


def test_nested_session_gate_reads_account_from_effective_variable_context(
    monkeypatch,
):
    captured: dict[str, object] = {}

    def fake_gate(**kwargs):
        captured.update(kwargs)
        return {
            "allowed": True,
            "ready": True,
            "reason": "facebook_session_ready",
        }

    monkeypatch.setattr(
        "tasks.scenario.steps.platform_session._observe_readiness",
        lambda *args, **kwargs: _readiness(PlatformReadinessStatus.READY),
    )
    monkeypatch.setattr(
        "services.platform_session_runtime.run_platform_session_gate",
        fake_gate,
    )
    sc = SimpleNamespace(
        var_ctx=VariableContext(scenario_vars={"__ACCOUNT_ID__": "account-1"}),
        ctx={"vars": {}},
        scenario={"platform": "facebook", "steps": [{"type": "platform_session_gate"}]},
        execution_id=None,
        serial="SERIAL1",
        cancel_event=None,
        device=SimpleNamespace(),
    )
    result = {"index": 0, "type": "platform_session_gate", "ok": True}

    handle_platform_session_gate(
        sc,
        {"id": "confirm", "type": "platform_session_gate", "phase": "confirm"},
        0,
        result,
    )

    assert result["ok"] is True
    assert captured["identity"] == {
        "account_id": "account-1",
        "execution_id": None,
        "step_id": "confirm",
        # The ledger records which phone ran the action, so the activity feed
        # can answer "what did this device do".
        "device_serial": "SERIAL1",
    }
    assert sc.ctx["vars"]["PLATFORM_SESSION_READY"] is True


@pytest.mark.asyncio
async def test_runtime_target_resolves_account_org_before_tenant_scope(
    session_factory,
    monkeypatch,
):
    async with session_factory() as db:
        with use_tenant_scope("org-1"):
            db.add(
                Account(
                    id="account-1",
                    org_id="org-1",
                    platform="facebook",
                    username="account-1",
                )
            )
            db.add(Device(id="device-1", org_id="org-1", serial="SERIAL1"))
            await db.commit()

        monkeypatch.setenv("TENANCY_STRICT_MODE", "true")
        with tenant_context(None):
            target = await _resolve_runtime_target(
                db,
                identity={"account_id": "account-1", "execution_id": None},
                device_serial="SERIAL1",
            )

    assert target == ("org-1", "device-1", "account-1")


@pytest.mark.asyncio
async def test_preflight_logged_out_requests_login(session_factory):
    async with session_factory() as db:
        with use_tenant_scope("org-1"):
            decision = await apply_platform_session_gate(
                db,
                org_id="org-1",
                device_id="device-1",
                account_id="account-1",
                phase="preflight",
                readiness=_readiness(PlatformReadinessStatus.LOGGED_OUT),
            )
            session = await get_platform_session(
                db, org_id="org-1", device_id="device-1"
            )

    assert decision["allowed"] is True
    assert decision["ready"] is False
    assert session is not None
    assert session.state == DevicePlatformSessionState.LOGIN_REQUIRED.value
    assert session.account_id is None


@pytest.mark.asyncio
async def test_confirm_requires_same_run_login_provenance(session_factory):
    async with session_factory() as db:
        with use_tenant_scope("org-1"):
            decision = await apply_platform_session_gate(
                db,
                org_id="org-1",
                device_id="device-1",
                account_id="account-1",
                phase="confirm",
                readiness=_readiness(PlatformReadinessStatus.READY),
                login_provenance=None,
            )

    assert decision["allowed"] is False
    assert decision["reason"] == "facebook_login_provenance_missing"


@pytest.mark.asyncio
async def test_confirm_marks_expected_account_active(session_factory):
    provenance = {
        "org_id": "org-1",
        "device_id": "device-1",
        "account_id": "account-1",
        "login_required": True,
    }
    async with session_factory() as db:
        with use_tenant_scope("org-1"):
            decision = await apply_platform_session_gate(
                db,
                org_id="org-1",
                device_id="device-1",
                account_id="account-1",
                phase="confirm",
                readiness=_readiness(PlatformReadinessStatus.READY),
                login_provenance=provenance,
            )
            session = await get_platform_session(
                db, org_id="org-1", device_id="device-1"
            )

    assert decision["allowed"] is True
    assert decision["ready"] is True
    assert session is not None
    assert session.state == DevicePlatformSessionState.ACTIVE.value
    assert session.account_id == "account-1"
    assert session.establishment_method == "scenario_login"


@pytest.mark.asyncio
async def test_preflight_blocks_another_active_account(session_factory):
    async with session_factory() as db:
        with use_tenant_scope("org-1"):
            await mark_active(
                db,
                org_id="org-1",
                device_id="device-1",
                account_id="account-other",
                establishment_method="test",
                reason="test",
            )
            decision = await apply_platform_session_gate(
                db,
                org_id="org-1",
                device_id="device-1",
                account_id="account-1",
                phase="preflight",
                readiness=_readiness(PlatformReadinessStatus.READY),
            )

    assert decision["allowed"] is False
    assert decision["reason"] == "facebook_session_account_mismatch"


def test_only_recoverable_guard_reasons_are_deferred_to_login():
    assert guard_reason_allows_login_recovery("facebook_session_login_required") is True
    assert guard_reason_allows_login_recovery("facebook_session_missing") is True
    assert (
        guard_reason_allows_login_recovery("facebook_session_account_mismatch") is False
    )
    assert guard_reason_allows_login_recovery("facebook_session_checkpoint") is False


def test_registry_gate_detection_follows_selected_run_scenario_only():
    login = {"steps": [{"type": "platform_session_gate", "phase": "preflight"}]}
    selected = {
        "steps": [
            {"type": "run_scenario", "scenario_name": "Đăng nhập Facebook"},
            {"type": "wait", "seconds": 1},
        ]
    }
    registry = {
        "by_id": {"selected": selected, "other": {"steps": []}},
        "by_campaign_name": {},
        "by_template_name": {"Đăng nhập Facebook": login},
    }

    assert (
        scenario_registry_has_platform_login_gate(
            registry, [{"scenario_id": "selected"}]
        )
        is True
    )
    assert (
        scenario_registry_has_platform_login_gate(registry, [{"scenario_id": "other"}])
        is False
    )


def test_platform_session_requirements_are_platform_neutral():
    assert platform_session_requirement_platforms(
        {
            "requirements": {
                "platform_session": {
                    "required": True,
                    "platform": "facebook",
                }
            }
        }
    ) == {"facebook"}
    assert platform_session_requirement_platforms(
        {"tags": "facebook,nurture,requires-platform-session:facebook"}
    ) == {"facebook"}


def test_registry_collects_platform_session_requirements_from_dependencies():
    selected = {
        "steps": [{"type": "run_scenario", "scenario_name": "Child"}],
        "requirements": {
            "platform_session": {"required": True, "platform": "facebook"}
        },
    }
    child = {"steps": [], "tags": "requires-platform-session:tiktok"}
    registry = {
        "by_id": {"selected": selected},
        "by_campaign_name": {},
        "by_template_name": {"Child": child},
    }

    assert scenario_registry_platform_session_requirements(
        registry, [{"scenario_id": "selected"}]
    ) == {"facebook", "tiktok"}


def test_template_clone_body_preserves_platform_session_requirement():
    from services.org_scenario_io.service import _template_body_json

    body = _template_body_json(
        SimpleNamespace(
            steps=[{"type": "wait", "seconds": 1}],
            nodes=[],
            edges=[],
            variables={},
            tags="facebook,requires-platform-session:facebook",
        )
    )

    assert body["requirements"]["platform_session"] == {
        "required": True,
        "platform": "facebook",
        "account_source": "device_primary",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "expected_unavailable"),
    [
        ("facebook_session_missing", False),
        ("facebook_session_login_required", False),
        ("facebook_session_account_mismatch", True),
        ("facebook_session_checkpoint", True),
    ],
)
async def test_dispatch_defers_only_login_recoverable_session_blocks(
    monkeypatch,
    reason: str,
    expected_unavailable: bool,
):
    async def fake_guard(*_args, **_kwargs):
        return FacebookSessionGuardDecision(
            mode=FacebookSessionGuardMode.ENFORCE,
            outcome=FacebookSessionGuardOutcome.BLOCK,
            reason=reason,
            checked_at=datetime.now(timezone.utc),
            expected_account_id="account-1",
        )

    monkeypatch.setattr(
        "services.platform_session_guard.guard_platform_session", fake_guard
    )
    resolved = ResolvedDeviceAccount(account_id="account-1", account_vars={})

    result = await _apply_platform_session_guard_to_accounts(
        None,
        org_id="org-1",
        platform="facebook",
        account_by_device={"device-1": resolved},
        device_map={"device-1": SimpleNamespace(serial="SERIAL-1")},
        allow_login_recovery=True,
    )

    assert result["device-1"].unavailable is expected_unavailable
    assert bool(
        (result["device-1"].session_guard or {}).get("deferred_to_scenario_login")
    ) is (not expected_unavailable)


def test_scrolled_feed_is_recognised_as_ready() -> None:
    """Facebook hides the tab bar and composer once the feed is scrolled.

    A logged-in account reading its own feed then had no ready marker at all,
    so `platform_session_gate` blocked every scenario with
    readiness_markers_not_found — observed on a real device.
    """
    from services.facebook_readiness import (
        PlatformReadinessStatus,
        resolve_facebook_readiness,
    )

    xml = (
        "<hierarchy>"
        '<node text="Thích" content-desc="Thích" package="com.facebook.katana" />'
        '<node text="Bình luận" content-desc="Bình luận" package="com.facebook.katana" />'
        '<node text="Chia sẻ" content-desc="Chia sẻ" package="com.facebook.katana" />'
        "</hierarchy>"
    )

    result = resolve_facebook_readiness(xml)

    assert result.status is PlatformReadinessStatus.READY


def test_login_screen_still_wins_over_the_widened_ready_markers() -> None:
    """Widening ready markers must not let a login surface read as ready."""
    from services.facebook_readiness import (
        PlatformReadinessStatus,
        resolve_facebook_readiness,
    )

    xml = (
        "<hierarchy>"
        '<node text="Đăng nhập Facebook" package="com.facebook.katana" />'
        '<node text="Mật khẩu" package="com.facebook.katana" />'
        '<node text="Chia sẻ" package="com.facebook.katana" />'
        "</hierarchy>"
    )

    result = resolve_facebook_readiness(xml)

    assert result.status is PlatformReadinessStatus.LOGGED_OUT
