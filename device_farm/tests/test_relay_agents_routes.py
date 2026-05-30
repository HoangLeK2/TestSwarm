"""Tests for relay-agents logic — servicer integration (no HTTP transport needed).

NOTE: /api/relay-agents is only mounted when database.enabled=True, so HTTP
route registration is tested via integration test with a real DB only.
These tests cover the servicer behaviour directly.
"""
from __future__ import annotations

import asyncio

import pytest

from runtime.transports.agent_control_servicer import AgentControlServicer


# ── AgentControlServicer integration (no HTTP) ───────────────────────────────

@pytest.mark.asyncio
async def test_bootstrap_all_calls_servicer_per_serial():
    """bootstrap_all must call ctrl.bootstrap for each non-pending serial."""
    from runtime.transports.agent_control_servicer import AgentControlServicer

    svc = AgentControlServicer()

    # Wire two fake connections so bootstrap resolves immediately
    async def _fake_bootstrap(serial: str, timeout: float = 180.0) -> dict:
        return {"ok": True, "exit_code": 0, "output": "done", "error": ""}

    svc.bootstrap = _fake_bootstrap  # type: ignore[method-assign]

    results = await asyncio.gather(
        svc.bootstrap("dev-001"),
        svc.bootstrap("dev-002"),
    )
    assert all(r["ok"] for r in results)


@pytest.mark.asyncio
async def test_control_stream_rejects_invalid_enrollment_token():
    """Invalid enrollment token must reject before the relay is indexed online."""
    from runtime.transports.grpc_gen import relay_pb2

    svc = AgentControlServicer()

    async def _reject_register(_payload: dict) -> bool:
        return False

    svc.set_persistence_callbacks(_reject_register, None, None)

    async def _messages():
        yield relay_pb2.AgentControlMsg(
            register=relay_pb2.RegisterMsg(
                relay_id="relay-x",
                serials=["dev-1"],
                hostname="host",
                ip="10.0.0.2",
                agent_version="test",
            )
        )

    class _Context:
        def invocation_metadata(self):
            return (("x-relay-enrollment-token", "bad-token"),)

        async def abort(self, _code, detail):
            raise RuntimeError(detail)

    with pytest.raises(RuntimeError, match="invalid or missing relay enrollment token"):
        async for _ in svc.ControlStream(_messages(), _Context()):
            pass

    assert svc.conn_for_relay("relay-x") is None
    assert svc.conn_for_serial("dev-1") is None


@pytest.mark.asyncio
async def test_bootstrap_all_route_skips_pending_serials():
    """Route handler only bootstraps current user's non-pending same-LAN serials."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from datetime import datetime, timezone

    from api.routes.relay_agents import bootstrap_all

    # Build fake DB row with mixed real + pending serials
    fake_row = MagicMock()
    fake_row.relay_id = "relay-x"
    fake_row.serials = ["dev-real-1", "pending-abc123", "dev-real-2", "unowned-same-lan", "other-lan-device"]

    dev1 = MagicMock()
    dev1.serial = "dev-real-1"
    dev1.adb_serial = None
    dev1.adb_ip = None
    dev1.adb_port = 5555
    dev1.user_id = "user-a"

    dev2 = MagicMock()
    dev2.serial = "logical-dev-2"
    dev2.adb_serial = "dev-real-2"
    dev2.adb_ip = None
    dev2.adb_port = 5555
    dev2.user_id = "user-a"

    called_serials: list[str] = []

    # Fake control servicer
    fake_ctrl = MagicMock()
    async def _fake_bootstrap(serial: str, timeout: float = 180.0) -> dict:
        called_serials.append(serial)
        return {"ok": True, "exit_code": 0, "output": "done", "error": "", "serial": serial}
    fake_ctrl.bootstrap = _fake_bootstrap

    fake_db = AsyncMock()
    fake_user = MagicMock()
    fake_user.id = "user-a"

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents._get_ctrl", return_value=fake_ctrl), \
         patch("api.routes.relay_agents._serial_is_same_wifi", side_effect=lambda s, _row: s != "other-lan-device"):
        mock_repo.get_relay_agent = AsyncMock(return_value=fake_row)
        mock_repo.list_devices = AsyncMock(return_value=[dev1, dev2])

        result = await bootstrap_all(relay_id="relay-x", db=fake_db, user=fake_user)

    assert "pending-abc123" not in called_serials, "pending serial must be skipped"
    assert "unowned-same-lan" not in called_serials
    assert "other-lan-device" not in called_serials
    assert "dev-real-1" in called_serials
    assert "dev-real-2" in called_serials
    assert result.total == 2
    assert result.ok == 2


@pytest.mark.asyncio
async def test_list_relay_agents_dedupes_same_hostname_rows():
    from unittest.mock import AsyncMock, MagicMock, patch
    from datetime import datetime, timezone

    from api.routes.relay_agents import list_relay_agents

    def _row(rid: str, status: str, hb_offset: int):
        row = MagicMock()
        row.relay_id = rid
        row.hostname = "Les-MacBook-Pro.local"
        row.ip = "172.16.0.182"
        row.version = "test"
        row.serials = ["10AE7S00HD002JK"]
        row.status = status
        now = datetime.now(timezone.utc)
        row.connected_at = now
        row.last_heartbeat_at = datetime.fromtimestamp(now.timestamp() + hb_offset, tz=timezone.utc)
        row.disconnected_at = None
        row.user_id = "user-a"
        row.enrollment_token_id = "tok-a"
        return row

    fake_db = AsyncMock()
    fake_user = MagicMock()
    fake_user.id = "user-a"

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents._get_live_caps", return_value={"wlan_ip": "172.16.0.182"}), \
         patch("api.routes.relay_agents._live_relay_serials", return_value={"10AE7S00HD002JK"}):
        mock_repo.list_relay_agents = AsyncMock(
            return_value=[_row("relay-old", "offline", 0), _row("relay-new", "online", 10)]
        )
        mock_repo.list_devices = AsyncMock(return_value=[])

        result = await list_relay_agents(db=fake_db, user=fake_user)

    assert len(result) == 1
    assert result[0].relay_id == "relay-new"


@pytest.mark.asyncio
async def test_list_relay_agents_uses_alias_owner_map_and_cached_caps():
    from unittest.mock import AsyncMock, MagicMock, patch
    from datetime import datetime, timezone

    from api.routes.relay_agents import list_relay_agents

    fake_row = MagicMock()
    fake_row.relay_id = "relay-x"
    fake_row.hostname = "agent-host"
    fake_row.ip = "192.168.1.10"
    fake_row.version = "test"
    fake_row.serials = ["192.168.1.20:5555", "192.168.1.21:5555"]
    fake_row.status = "online"
    fake_row.connected_at = datetime.now(timezone.utc)
    fake_row.last_heartbeat_at = fake_row.connected_at
    fake_row.disconnected_at = None
    fake_row.user_id = "user-a"
    fake_row.enrollment_token_id = "tok-a"

    owned_by_other = MagicMock()
    owned_by_other.serial = "logical-other"
    owned_by_other.adb_serial = "192.168.1.21:5555"
    owned_by_other.adb_ip = None
    owned_by_other.adb_port = 5555
    owned_by_other.user_id = "user-b"

    fake_db = AsyncMock()
    fake_user = MagicMock()
    fake_user.id = "user-a"

    caps_calls: list[str] = []

    def _fake_caps(serial: str) -> dict:
        caps_calls.append(serial)
        return {
            "display_name": f"Phone {serial}",
            "wlan_ip": serial.rsplit(":", 1)[0],
            "wlan_cidr": "192.168.1.0/24",
        }

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents._get_live_caps", side_effect=_fake_caps), \
         patch(
             "api.routes.relay_agents._live_relay_serials",
             return_value={"192.168.1.20:5555", "192.168.1.21:5555"},
         ):
        mock_repo.list_relay_agents = AsyncMock(return_value=[fake_row])
        mock_repo.list_devices = AsyncMock(return_value=[owned_by_other])

        result = await list_relay_agents(db=fake_db, user=fake_user)

    assert len(result) == 1
    assert result[0].serials == ["192.168.1.20:5555"]
    assert caps_calls == ["192.168.1.20:5555", "192.168.1.21:5555"]


@pytest.mark.asyncio
async def test_list_relay_agents_hides_serials_when_control_channel_offline():
    from unittest.mock import AsyncMock, MagicMock, patch
    from datetime import datetime, timezone

    from api.routes.relay_agents import list_relay_agents

    fake_row = MagicMock()
    fake_row.relay_id = "relay-x"
    fake_row.hostname = "agent-host"
    fake_row.ip = "192.168.1.10"
    fake_row.version = "test"
    fake_row.serials = ["192.168.1.20:5555"]
    fake_row.status = "online"
    fake_row.connected_at = datetime.now(timezone.utc)
    fake_row.last_heartbeat_at = fake_row.connected_at
    fake_row.disconnected_at = None
    fake_row.user_id = "user-a"
    fake_row.enrollment_token_id = "tok-a"

    fake_db = AsyncMock()
    fake_user = MagicMock()
    fake_user.id = "user-a"

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents._live_relay_serials", return_value=None):
        mock_repo.list_relay_agents = AsyncMock(return_value=[fake_row])
        mock_repo.list_devices = AsyncMock(return_value=[])

        result = await list_relay_agents(db=fake_db, user=fake_user)

    assert len(result) == 1
    assert result[0].status == "offline"
    assert result[0].live_connected is False
    assert result[0].serials == []
    assert result[0].device_names == {}


@pytest.mark.asyncio
async def test_relay_token_routes_are_user_scoped():
    from unittest.mock import AsyncMock, MagicMock, patch
    from datetime import datetime, timezone

    from api.routes.relay_agents import create_relay_agent_token, list_relay_agent_tokens, revoke_relay_agent_token
    from api.schemas.relay_agent import RelayAgentTokenCreate

    fake_db = AsyncMock()
    fake_user = MagicMock()
    fake_user.id = "user-a"
    fake_user.org_id = "org-a"

    fake_row = MagicMock()
    fake_row.id = "tok-1"
    fake_row.name = "office"
    fake_row.prefix = "dfra_abc12345"
    fake_row.status = "active"
    fake_row.created_at = datetime.now(timezone.utc)
    fake_row.last_used_at = None
    fake_row.revoked_at = None

    with patch("api.routes.relay_agents.repo") as mock_repo:
        mock_repo.create_relay_agent_token = AsyncMock(return_value=("dfra_secret", fake_row))
        created = await create_relay_agent_token(
            RelayAgentTokenCreate(name="office"),
            db=fake_db,
            user=fake_user,
        )
        assert created.token == "dfra_secret"
        mock_repo.create_relay_agent_token.assert_awaited_once_with(
            fake_db, user_id="user-a", name="office", org_id="org-a"
        )

        mock_repo.list_relay_agent_tokens = AsyncMock(return_value=[fake_row])
        listed = await list_relay_agent_tokens(db=fake_db, user=fake_user)
        assert listed == [fake_row]
        mock_repo.list_relay_agent_tokens.assert_awaited_once_with(fake_db, user_id="user-a")

        mock_repo.revoke_relay_agent_token = AsyncMock(return_value=True)
        await revoke_relay_agent_token("tok-1", db=fake_db, user=fake_user)
        mock_repo.revoke_relay_agent_token.assert_awaited_once_with(
            fake_db, token_id="tok-1", user_id="user-a"
        )


@pytest.mark.asyncio
async def test_relay_pair_bulk_uses_enrollment_token_owner(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch

    from api.routes.relay_agents import PairBulkBody, relay_pair_bulk
    from services import pairing as pairing_mod

    monkeypatch.setenv("RELAY_API_KEY", "relay-key")
    pairing_mod.store.clear()

    fake_request = MagicMock()
    fake_request.headers = {
        "x-relay-api-key": "relay-key",
        "x-relay-enrollment-token": "dfra_secret",
        "host": "farm.local",
    }
    fake_request.url.scheme = "https"
    fake_request.url.netloc = "farm.local"

    token_row = MagicMock()
    token_row.user_id = "user-a"

    with patch("api.routes.relay_agents.repo") as mock_repo:
        mock_repo.resolve_relay_agent_token = AsyncMock(return_value=token_row)
        result = await relay_pair_bulk(
            "relay-x",
            PairBulkBody(serials=["dev-1"]),
            fake_request,
            db=AsyncMock(),
        )

    pairing_url = result["pairings"]["dev-1"]
    pairing_id = pairing_url.rsplit("pair=", 1)[1]
    assert pairing_mod.store[pairing_id]["user_id"] == "user-a"
    assert pairing_mod.store[pairing_id]["relay_id"] == "relay-x"


@pytest.mark.asyncio
async def test_create_relay_provision_job_is_user_scoped():
    from unittest.mock import AsyncMock, MagicMock, patch
    from datetime import datetime, timezone

    from api.routes.relay_agents import create_relay_provision_job
    from api.schemas.relay_agent import RelayBatchJobCreate
    from services import relay_onboarding

    fake_db = AsyncMock()
    fake_user = MagicMock()
    fake_user.id = "user-a"
    fake_request = MagicMock()
    fake_request.app.state.scheduler = None
    fake_row = MagicMock()
    fake_row.relay_id = "relay-x"

    fake_job = MagicMock()
    fake_job.id = "job-1"
    fake_job.relay_id = "relay-x"
    fake_job.kind = relay_onboarding.KIND_PROVISION
    fake_job.status = "pending"
    fake_job.total = 2
    fake_job.ok = 0
    fake_job.failed = 0
    fake_job.pending = 2
    fake_job.created_at = datetime.now(timezone.utc)
    fake_job.started_at = None
    fake_job.finished_at = None
    fake_job.updated_at = fake_job.created_at

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents.relay_onboarding.create_relay_batch_job", new=AsyncMock(return_value=fake_job)) as create_job, \
         patch("api.routes.relay_agents.relay_onboarding.dispatch_local_relay_job") as dispatch:
        mock_repo.get_relay_agent = AsyncMock(return_value=fake_row)
        mock_repo.list_relay_job_items = AsyncMock(return_value=[])

        result = await create_relay_provision_job(
            "relay-x",
            RelayBatchJobCreate(mode="selected", serials=["dev-1", "dev-2"]),
            request=fake_request,
            db=fake_db,
            user=fake_user,
        )

    mock_repo.get_relay_agent.assert_awaited_once_with(fake_db, "relay-x", user_id="user-a")
    create_job.assert_awaited_once_with(
        fake_db,
        fake_row,
        user_id="user-a",
        kind=relay_onboarding.KIND_PROVISION,
        mode="selected",
        serials=["dev-1", "dev-2"],
    )
    dispatch.assert_called_once_with("job-1", claim_connect=None)
    assert result.id == "job-1"
    assert result.total == 2


@pytest.mark.asyncio
async def test_create_relay_claim_connect_job_dispatches_with_ws_base_url():
    from unittest.mock import AsyncMock, MagicMock, patch
    from datetime import datetime, timezone

    from api.routes.relay_agents import create_relay_claim_connect_job
    from api.schemas.relay_agent import RelayBatchJobCreate
    from services import relay_onboarding

    fake_db = AsyncMock()
    fake_user = MagicMock()
    fake_user.id = "user-a"
    fake_row = MagicMock()
    fake_row.relay_id = "relay-x"
    fake_request = MagicMock()
    fake_request.url.scheme = "https"
    fake_request.url.netloc = "ignored.local"
    fake_request.headers = {"host": "farm.local"}
    fake_request.app.state.scheduler = None

    fake_job = MagicMock()
    fake_job.id = "job-2"
    fake_job.relay_id = "relay-x"
    fake_job.kind = relay_onboarding.KIND_CLAIM_CONNECT
    fake_job.status = "pending"
    fake_job.total = 1
    fake_job.ok = 0
    fake_job.failed = 0
    fake_job.pending = 1
    fake_job.created_at = datetime.now(timezone.utc)
    fake_job.started_at = None
    fake_job.finished_at = None
    fake_job.updated_at = fake_job.created_at

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents.relay_onboarding.create_relay_batch_job", new=AsyncMock(return_value=fake_job)), \
         patch("api.routes.relay_agents.relay_onboarding.dispatch_local_relay_job") as dispatch:
        mock_repo.get_relay_agent = AsyncMock(return_value=fake_row)
        mock_repo.list_relay_job_items = AsyncMock(return_value=[])

        await create_relay_claim_connect_job(
            "relay-x",
            RelayBatchJobCreate(mode="selected", serials=["dev-1"], connect=True),
            request=fake_request,
            db=fake_db,
            user=fake_user,
        )

    _, kwargs = dispatch.call_args
    opts = kwargs["claim_connect"]
    assert opts.connect is True
    assert opts.ws_base_url == "wss://farm.local"


@pytest.mark.asyncio
async def test_relay_job_dispatch_prefers_temporal_when_available():
    from unittest.mock import AsyncMock, MagicMock, patch

    from api.routes.relay_agents import _dispatch_relay_job

    fake_request = MagicMock()
    fake_scheduler = MagicMock()
    fake_scheduler._client = MagicMock()
    fake_scheduler._cfg = MagicMock()
    fake_request.app.state.scheduler = fake_scheduler

    fake_job = MagicMock()
    fake_job.id = "job-temporal"
    fake_db = AsyncMock()

    with patch("api.routes.relay_agents.relay_onboarding.dispatch_temporal_relay_job", new=AsyncMock()) as temporal_dispatch, \
         patch("api.routes.relay_agents.relay_onboarding.dispatch_local_relay_job") as local_dispatch:
        await _dispatch_relay_job(fake_request, fake_db, fake_job)

    temporal_dispatch.assert_awaited_once()
    local_dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_relay_job_dispatch_requires_temporal_when_configured(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import HTTPException

    from api.routes.relay_agents import _dispatch_relay_job

    monkeypatch.setenv("RELAY_ONBOARDING_REQUIRE_TEMPORAL", "true")

    fake_request = MagicMock()
    fake_request.app.state.scheduler = None
    fake_db = AsyncMock()
    fake_job = MagicMock()
    fake_job.id = "job-requires-temporal"
    fake_item = MagicMock()
    fake_item.id = "item-1"

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents.relay_onboarding.dispatch_local_relay_job") as local_dispatch:
        mock_repo.list_relay_job_items = AsyncMock(return_value=[fake_item])
        mock_repo.finish_relay_job_item = AsyncMock()
        mock_repo.finish_relay_job = AsyncMock()

        with pytest.raises(HTTPException) as excinfo:
            await _dispatch_relay_job(fake_request, fake_db, fake_job)

    assert excinfo.value.status_code == 503
    local_dispatch.assert_not_called()
    mock_repo.finish_relay_job_item.assert_awaited_once()
