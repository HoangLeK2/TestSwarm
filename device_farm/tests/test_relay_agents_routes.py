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
    fake_user.org_id = "org-a"

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
async def test_register_relay_device_schedules_bootstrap_after_claim():
    from unittest.mock import patch

    from api.routes.relay_agents import _schedule_bootstrap_for_registered_relay_device

    called: list[str] = []

    class FakeControl:
        async def bootstrap(self, serial: str, timeout: float = 180.0) -> dict:
            called.append(serial)
            return {"ok": True, "exit_code": 0, "output": "ready", "error": ""}

    with patch("api.routes.relay_agents._get_ctrl_optional", return_value=FakeControl()):
        assert _schedule_bootstrap_for_registered_relay_device("dev-registered")
        await asyncio.sleep(0)

    assert called == ["dev-registered"]


def test_register_relay_device_bootstrap_skip_without_control_servicer():
    from unittest.mock import patch

    from api.routes.relay_agents import _schedule_bootstrap_for_registered_relay_device

    with patch("api.routes.relay_agents._get_ctrl_optional", return_value=None):
        assert not _schedule_bootstrap_for_registered_relay_device("dev-registered")


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
    fake_user.org_id = "org-a"

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents._get_live_caps", return_value={"wlan_ip": "172.16.0.182"}), \
         patch("api.routes.relay_agents._live_relay_serials", return_value={"10AE7S00HD002JK"}):
        mock_repo.list_relay_agents = AsyncMock(
            return_value=[_row("relay-old", "offline", 0), _row("relay-new", "online", 10)]
        )
        mock_repo.list_devices_by_serial_aliases = AsyncMock(return_value=[])
        mock_repo.list_active_session_device_ids = AsyncMock(return_value=set())

        result = await list_relay_agents(db=fake_db, user=fake_user)

    mock_repo.list_relay_agents.assert_awaited_once_with(fake_db, org_id="org-a")
    assert len(result) == 1
    assert result[0].relay_id == "relay-new"


@pytest.mark.asyncio
async def test_list_relay_agents_uses_org_scope_and_cached_caps():
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

    fake_db = AsyncMock()
    fake_user = MagicMock()
    fake_user.id = "user-a"
    fake_user.org_id = "org-a"

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
        mock_repo.list_devices_by_serial_aliases = AsyncMock(return_value=[])
        mock_repo.list_active_session_device_ids = AsyncMock(return_value=set())

        result = await list_relay_agents(db=fake_db, user=fake_user)

    mock_repo.list_relay_agents.assert_awaited_once_with(fake_db, org_id="org-a")
    assert len(result) == 1
    assert result[0].serials == ["192.168.1.20:5555", "192.168.1.21:5555"]
    assert caps_calls == ["192.168.1.20:5555", "192.168.1.21:5555"]


@pytest.mark.asyncio
async def test_list_relay_agents_includes_registered_device_agent_connection_state():
    from unittest.mock import AsyncMock, MagicMock, patch
    from datetime import datetime, timezone

    from api.routes.relay_agents import list_relay_agents

    fake_row = MagicMock()
    fake_row.relay_id = "relay-x"
    fake_row.hostname = "agent-host"
    fake_row.ip = "192.168.1.10"
    fake_row.version = "test"
    fake_row.serials = ["10AE7S00HD002JK"]
    fake_row.status = "online"
    fake_row.connected_at = datetime.now(timezone.utc)
    fake_row.last_heartbeat_at = fake_row.connected_at
    fake_row.disconnected_at = None
    fake_row.user_id = "user-a"
    fake_row.enrollment_token_id = "tok-a"

    device = MagicMock()
    device.id = "device-1"
    device.serial = "logical-device"
    device.adb_serial = "10AE7S00HD002JK"
    device.adb_ip = None
    device.adb_port = 5555
    device.user_id = "user-a"
    device.org_id = "org-a"

    fake_db = AsyncMock()
    fake_user = MagicMock()
    fake_user.id = "user-a"
    fake_user.org_id = "org-a"

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents._get_live_caps", return_value={}), \
         patch("api.routes.relay_agents._live_relay_serials", return_value={"10AE7S00HD002JK"}):
        mock_repo.list_relay_agents = AsyncMock(return_value=[fake_row])
        mock_repo.list_devices_by_serial_aliases = AsyncMock(return_value=[device])
        mock_repo.list_active_session_device_ids = AsyncMock(return_value={"device-1"})

        result = await list_relay_agents(db=fake_db, user=fake_user)

    conn = result[0].device_connections["10AE7S00HD002JK"]
    assert conn.registered is True
    assert conn.device_id == "device-1"
    assert conn.device_agent_connected is True


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
    fake_user.org_id = "org-a"

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents._live_relay_serials", return_value=None):
        mock_repo.list_relay_agents = AsyncMock(return_value=[fake_row])
        mock_repo.list_devices_by_serial_aliases = AsyncMock(return_value=[])
        mock_repo.list_active_session_device_ids = AsyncMock(return_value=set())

        result = await list_relay_agents(db=fake_db, user=fake_user)

    mock_repo.list_relay_agents.assert_awaited_once_with(fake_db, org_id="org-a")
    assert len(result) == 1
    assert result[0].status == "offline"
    assert result[0].live_connected is False
    assert result[0].serials == []
    assert result[0].device_names == {}


def test_live_relay_serials_requires_video_relay_channel():
    from unittest.mock import MagicMock, patch

    from api.routes.relay_agents import _live_relay_serials

    fake_conn = MagicMock()
    fake_conn.serials = {"10AE7S00HD002JK"}

    fake_ctrl = MagicMock()
    fake_ctrl.conn_for_relay.return_value = fake_conn

    fake_relay = MagicMock()
    fake_relay.registered_relays.return_value = {}

    with patch("api.routes.relay_agents._get_ctrl_optional", return_value=fake_ctrl), \
         patch("api.routes.relay_agents._get_relay_manager_optional", return_value=fake_relay):
        assert _live_relay_serials("relay-x") is None


def test_live_relay_serials_intersects_video_and_control_serials():
    from unittest.mock import MagicMock, patch

    from api.routes.relay_agents import _live_relay_serials

    fake_conn = MagicMock()
    fake_conn.serials = {"10AE7S00HD002JK", "control-only"}

    fake_ctrl = MagicMock()
    fake_ctrl.conn_for_relay.return_value = fake_conn

    fake_relay = MagicMock()
    fake_relay.registered_relays.return_value = {
        "relay-x": ["10AE7S00HD002JK", "video-only"]
    }

    with patch("api.routes.relay_agents._get_ctrl_optional", return_value=fake_ctrl), \
         patch("api.routes.relay_agents._get_relay_manager_optional", return_value=fake_relay):
        assert _live_relay_serials("relay-x") == {"10AE7S00HD002JK"}


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
         patch("api.routes.relay_agents.device_farm_ws_public_base", return_value=""), \
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
async def test_connect_relay_device_pushes_device_agent_url_without_logging_key(caplog):
    from unittest.mock import AsyncMock, MagicMock, patch

    from api.routes.relay_agents import connect_relay_device

    row = MagicMock()
    row.status = "online"
    row.serials = ["dev-1"]

    device = MagicMock()
    device.id = "device-1"
    device.serial = "dev-1"
    device.adb_serial = "dev-1"
    device.adb_ip = None
    device.adb_port = 5555
    device.device_key = "secret-device-key"
    device.user_id = "user-a"
    device.org_id = "org-a"

    fake_ctrl = MagicMock()
    shell_calls: list[tuple[str, str]] = []

    async def _shell(serial: str, cmd: str, timeout: float = 15.0) -> dict:
        shell_calls.append((serial, cmd))
        return {"ok": True, "exit_code": 0, "output": "started", "error": ""}

    fake_ctrl.shell = _shell

    fake_request = MagicMock()
    fake_request.url.scheme = "https"
    fake_request.headers = {"host": "farm.local"}

    fake_db = AsyncMock()
    fake_user = MagicMock()
    fake_user.id = "user-a"
    fake_user.org_id = "org-a"

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents._get_ctrl", return_value=fake_ctrl):
        mock_repo.get_relay_agent = AsyncMock(return_value=row)
        mock_repo.list_devices = AsyncMock(return_value=[device])

        result = await connect_relay_device(
            "relay-x",
            "dev-1",
            request=fake_request,
            db=fake_db,
            user=fake_user,
        )

    assert result.ok is True
    assert shell_calls[0][0] == "dev-1"
    assert "ACTION_IDENTIFY" in shell_calls[0][1]
    assert "secret-device-key" in shell_calls[0][1]
    assert "secret-device-key" not in caplog.text


@pytest.mark.asyncio
async def test_disconnect_relay_device_force_stops_stf_and_closes_active_sessions():
    from unittest.mock import AsyncMock, MagicMock, patch

    from api.routes.relay_agents import disconnect_relay_device

    row = MagicMock()
    row.status = "online"
    row.serials = ["dev-1"]

    device = MagicMock()
    device.id = "device-1"
    device.serial = "dev-1"
    device.adb_serial = "dev-1"
    device.adb_ip = None
    device.adb_port = 5555
    device.user_id = "user-a"
    device.org_id = "org-a"

    fake_ctrl = MagicMock()
    shell_calls: list[tuple[str, str]] = []

    async def _shell(serial: str, cmd: str, timeout: float = 15.0) -> dict:
        shell_calls.append((serial, cmd))
        return {"ok": True, "exit_code": 0, "output": "", "error": ""}

    fake_ctrl.shell = _shell

    fake_db = AsyncMock()
    fake_user = MagicMock()
    fake_user.id = "user-a"
    fake_user.org_id = "org-a"

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents._get_ctrl", return_value=fake_ctrl):
        mock_repo.get_relay_agent = AsyncMock(return_value=row)
        mock_repo.list_devices = AsyncMock(return_value=[device])
        mock_repo.close_active_sessions_for_device = AsyncMock(return_value=1)

        result = await disconnect_relay_device(
            "relay-x",
            "dev-1",
            db=fake_db,
            user=fake_user,
        )

    assert result.ok is True
    assert shell_calls == [("dev-1", "am force-stop jp.co.cyberagent.stf")]
    mock_repo.close_active_sessions_for_device.assert_awaited_once_with(
        fake_db, "device-1"
    )
    fake_db.commit.assert_awaited_once()


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


def test_normalize_ws_base_url_accepts_dashboard_lan_origin(monkeypatch):
    from api.routes.relay_agents import _normalize_ws_base_url, _ws_base_for_push
    from unittest.mock import MagicMock

    assert _normalize_ws_base_url("ws://172.16.0.182:8081") == "ws://172.16.0.182:8081"
    assert (
        _normalize_ws_base_url("ws://172.16.0.182:8081/device-agent?key=abc")
        == "ws://172.16.0.182:8081"
    )
    assert _normalize_ws_base_url("http://bad") is None

    request = MagicMock()
    request.url.scheme = "http"
    request.headers.get.return_value = "localhost:3000"
    monkeypatch.setattr(
        "api.routes.relay_agents.device_farm_ws_public_base",
        lambda: "ws://127.0.0.1:8080",
    )
    assert (
        _ws_base_for_push(request, "ws://172.16.0.182:8081")
        == "ws://172.16.0.182:8081"
    )
    assert _ws_base_for_push(request, None) == "ws://127.0.0.1:8080"


def test_register_relay_device_brings_device_online_not_just_bootstrap():
    """Registration must emit the FSM online event, not only schedule a bootstrap.

    The relay already reports the serial online (checked against row.serials) and
    the device row now exists, so both facts needed for `online` are true at
    registration. Before this, the endpoint only scheduled a bootstrap, so the
    device stayed `unknown` until the agent happened to re-emit its online
    transition — proven live: forcing a registered device to `unknown` and
    calling register flipped it back to `online` with no agent restart.
    """
    import inspect

    from api.routes.relay_agents import _claim_relay_serial, register_relay_device

    # The online transition lives in the shared claim helper now, so both the
    # single and bulk endpoints get it. Guard the helper, and that the single
    # endpoint still commits after claiming.
    assert "apply_relay_online" in inspect.getsource(_claim_relay_serial), (
        "claim helper no longer advances the FSM to online — a device will sit "
        "in `unknown` until the agent restarts"
    )
    assert "db.commit()" in inspect.getsource(register_relay_device)


@pytest.mark.asyncio
async def test_register_relay_devices_bulk_partial_success():
    """One bad serial must not sink the others, and each is reported on its own.

    Mirrors the DLQ bulk-retry partial-success shape: a per-item results list.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from api.routes.relay_agents import (
        RegisterRelayDevicesBody,
        register_relay_devices_bulk,
    )

    row = MagicMock()
    row.status = "online"
    row.serials = ["emulator-5554", "emulator-5556"]  # 5558 is NOT reported

    fake_db = AsyncMock()
    fake_user = MagicMock()
    fake_user.id = "user-a"
    fake_user.org_id = "org-a"

    async def _claim(db, r, serial, user):
        # Mirror the real helper: reject a serial the agent does not report.
        if serial not in set(r.serials or []):
            raise ValueError("serial is not reported by this relay agent")
        return serial  # canonical == serial for emulators

    def _device(_db, serial):
        d = MagicMock()
        d.id = f"id-{serial}"
        d.name = serial
        return d

    booted: list[str] = []

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents._claim_relay_serial", side_effect=_claim), \
         patch(
             "api.routes.relay_agents._schedule_bootstrap_for_registered_relay_device",
             side_effect=lambda s: booted.append(s) or True,
         ):
        mock_repo.get_relay_agent = AsyncMock(return_value=row)
        mock_repo.get_device_by_serial = AsyncMock(side_effect=_device)

        out = await register_relay_devices_bulk(
            relay_id="relay-x",
            body=RegisterRelayDevicesBody(serials=["emulator-5554", "emulator-5558"]),
            db=fake_db,
            user=fake_user,
        )

    by_serial = {r.serial: r for r in out.results}
    assert by_serial["emulator-5554"].status == "registered"
    assert by_serial["emulator-5554"].device_id == "id-emulator-5554"
    assert by_serial["emulator-5558"].status == "failed"
    assert "not reported" in (by_serial["emulator-5558"].message or "")
    # Only the successful one is bootstrapped.
    assert booted == ["emulator-5554"]


@pytest.mark.asyncio
async def test_register_relay_devices_bulk_empty_means_all_reported():
    """An empty serials list registers everything the agent reports."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from api.routes.relay_agents import (
        RegisterRelayDevicesBody,
        register_relay_devices_bulk,
    )

    row = MagicMock()
    row.status = "online"
    row.serials = ["emulator-5554", "emulator-5556", "emulator-5558"]

    fake_db = AsyncMock()
    fake_user = MagicMock()
    fake_user.id = "user-a"
    fake_user.org_id = "org-a"

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents._claim_relay_serial", side_effect=lambda db, r, s, u: s), \
         patch("api.routes.relay_agents._schedule_bootstrap_for_registered_relay_device", return_value=True):
        mock_repo.get_relay_agent = AsyncMock(return_value=row)
        mock_repo.get_device_by_serial = AsyncMock(
            side_effect=lambda _db, s: MagicMock(id=f"id-{s}", name=s)
        )

        out = await register_relay_devices_bulk(
            relay_id="relay-x",
            body=RegisterRelayDevicesBody(serials=[]),
            db=fake_db,
            user=fake_user,
        )

    assert [r.serial for r in out.results] == row.serials
    assert all(r.status == "registered" for r in out.results)


@pytest.mark.asyncio
async def test_register_relay_devices_bulk_rejects_offline_agent():
    from unittest.mock import AsyncMock, MagicMock, patch

    import pytest as _pytest
    from fastapi import HTTPException

    from api.routes.relay_agents import (
        RegisterRelayDevicesBody,
        register_relay_devices_bulk,
    )

    with patch("api.routes.relay_agents.repo") as mock_repo:
        mock_repo.get_relay_agent = AsyncMock(return_value=None)
        with _pytest.raises(HTTPException) as ei:
            await register_relay_devices_bulk(
                relay_id="relay-x",
                body=RegisterRelayDevicesBody(serials=["emulator-5554"]),
                db=AsyncMock(),
                user=MagicMock(id="user-a", org_id="org-a"),
            )
    assert ei.value.status_code == 404


# ── Route wiring ─────────────────────────────────────────────────────────────
#
# Every other test in this file calls the handler function directly, which is
# how a broken route survived: `_claim_relay_serial` was extracted as a shared
# helper and landed *between* the decorator and `register_relay_device`, so the
# decorator bound the route to the helper. FastAPI then read the helper's
# signature — `db`, `row` and `user` are untyped, so it demanded them as query
# parameters and answered every agent-boot registration with 422 before any
# handler code ran. These tests assert the wiring itself.

def _route_for(path_suffix: str):
    from api.routes.relay_agents import router

    matches = [r for r in router.routes if getattr(r, "path", "") == path_suffix]
    assert len(matches) == 1, f"expected exactly one route for {path_suffix}"
    return matches[0]


def test_single_register_route_is_bound_to_its_handler():
    from api.routes.relay_agents import register_relay_device

    route = _route_for("/relay-agents/{relay_id}/devices/{serial}/register")
    assert route.endpoint is register_relay_device


def test_register_routes_take_no_query_parameters():
    """A DB session or ORM row leaking into the signature becomes a required
    query parameter, which no client can ever satisfy."""
    for path in (
        "/relay-agents/{relay_id}/devices/{serial}/register",
        "/relay-agents/{relay_id}/devices/register",
    ):
        route = _route_for(path)
        leaked = [param.name for param in route.dependant.query_params]
        assert leaked == [], f"{path} exposes query params: {leaked}"


def test_single_register_route_reads_its_body_and_path():
    route = _route_for("/relay-agents/{relay_id}/devices/{serial}/register")
    assert {param.name for param in route.dependant.path_params} == {
        "relay_id",
        "serial",
    }
    assert route.body_field is not None
