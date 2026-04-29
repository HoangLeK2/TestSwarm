"""
tests/test_auth_security.py — Unit / integration tests for the 3 security fixes.

Fix 1: /api/tasks always requires JWT (even when db_enabled=False)
Fix 2: Device control routes check serial ownership (db_enabled=True only)
Fix 3: GET /api/tasks filtered by user's device serials (db_enabled=True)

All DB calls and JWT key reads are mocked — no real database required.
Run: pytest tests/test_auth_security.py -v
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from jose import jwt

# ---------------------------------------------------------------------------
# Constants — deterministic JWT signing key used in every test
# ---------------------------------------------------------------------------

_SECRET = "test-secret-key-long-enough-for-hs256-tests"
_ALG = "HS256"

@contextmanager
def _jwt_patch():
    """Patch jwt_secret_key / jwt_algorithm in all consumer modules."""
    with (
        patch("api.routes.public.jwt_secret_key", return_value=_SECRET),
        patch("api.routes.public.jwt_algorithm", return_value=_ALG),
        patch("api.auth.context.jwt_secret_key", return_value=_SECRET),
        patch("api.auth.context.jwt_algorithm", return_value=_ALG),
    ):
        yield


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _token(user_id: str = "user-1", token_type: str = "access",
           expire_minutes: int = 30) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    return jwt.encode(
        {"sub": user_id, "type": token_type, "exp": exp},
        _SECRET, algorithm=_ALG,
    )


def _auth(user_id: str = "user-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _FakeDevice:
    def __init__(self, serial: str, user_id: str = "user-1") -> None:
        self.serial = serial
        self.user_id = user_id


class _FakeTask:
    def __init__(self, task_id: str, target: str | None, name: str = "") -> None:
        self.id = task_id
        self.target = target
        self.name = name
        self.priority = 5
        self.status = MagicMock(value="PENDING")
        self.created_at = datetime.now(timezone.utc)
        self.started_at = None
        self.finished_at = None
        self.timeout = 30.0
        self.max_retries = 1
        self.retry_count = 0
        self.result = None
        self.error = None
        self.fn = lambda d: None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "target": self.target, "name": self.name}


def _mock_queue(tasks: list[_FakeTask] | None = None):
    q = MagicMock()
    q.all_tasks.return_value = tasks or []
    return q


def _mock_manager():
    m = MagicMock()
    m.all_devices.return_value = []
    return m


# ---------------------------------------------------------------------------
# DB mock: patches AsyncSessionLocal + repo.list_devices
# ---------------------------------------------------------------------------

@contextmanager
def _db_patch(db_devices: list[_FakeDevice]):
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session_cls = MagicMock(return_value=mock_session)

    async def fake_list_devices(db, user_id=None):
        if user_id is None:
            return list(db_devices)
        return [d for d in db_devices if d.user_id == user_id]

    async def fake_assert_owns_device(ctx, serial: str):
        allowed = {d.serial for d in db_devices if d.user_id == ctx.user_id}
        if serial not in allowed:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Not authorized for this device")

    with (
        patch("api.routes.public.AsyncSessionLocal", mock_session_cls),
        patch("api.routes.public.repo.list_devices", side_effect=fake_list_devices),
        patch("api.deps.policy.assert_owns_device", side_effect=fake_assert_owns_device),
    ):
        yield


# ---------------------------------------------------------------------------
# App factories
# ---------------------------------------------------------------------------

def _make_public_app(db_enabled: bool, queue=None):
    from core.config import Config
    from api.routes.public import build_public_router
    app = FastAPI()
    q = queue or _mock_queue()
    router = build_public_router(_mock_manager(), q, Config(), db_enabled)
    app.include_router(router)
    return app


def _make_device_control_app(db_enabled: bool):
    """Minimal app with one /tap/{serial} route + device_auth dependency."""
    from fastapi import Depends
    from api.deps import make_device_auth_dependency

    app = FastAPI()
    from fastapi import APIRouter
    router = APIRouter()

    @router.post("/tap/{serial}")
    async def fake_tap(serial: str):
        return {"ok": True, "serial": serial}

    device_auth = make_device_auth_dependency(db_enabled)
    app.include_router(router, dependencies=[Depends(device_auth)])
    return app


# ═══════════════════════════════════════════════════════════════════════════════
# Fix 1: /api/tasks always requires JWT
# ═══════════════════════════════════════════════════════════════════════════════

class TestTasksAlwaysRequiresJWT:

    @pytest.mark.anyio
    async def test_no_token_db_disabled_returns_401(self):
        """No token, db=False → 401 (was previously public)."""
        with _jwt_patch():
            app = _make_public_app(db_enabled=False)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/tasks")
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_no_token_db_enabled_returns_401(self):
        """No token, db=True → 401."""
        with _jwt_patch(), _db_patch([]):
            app = _make_public_app(db_enabled=True)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/tasks")
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_valid_token_db_disabled_returns_200(self):
        """Valid token, db=False → 200 (lab mode: all tasks visible)."""
        tasks = [_FakeTask("t1", "serial-A"), _FakeTask("t2", "serial-B")]
        with _jwt_patch():
            app = _make_public_app(db_enabled=False, queue=_mock_queue(tasks))
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/tasks", headers=_auth())
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_valid_token_db_disabled_returns_all_tasks(self):
        """In lab mode, valid JWT → all tasks returned (no ownership filter)."""
        tasks = [_FakeTask("t1", "serial-A"), _FakeTask("t2", "serial-B")]
        with _jwt_patch():
            app = _make_public_app(db_enabled=False, queue=_mock_queue(tasks))
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/tasks", headers=_auth())
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.anyio
    async def test_refresh_token_returns_401(self):
        """Refresh tokens must be rejected even in lab mode."""
        token = _token(token_type="refresh")
        with _jwt_patch():
            app = _make_public_app(db_enabled=False)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/tasks", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_expired_token_returns_401(self):
        token = _token(expire_minutes=-1)
        with _jwt_patch():
            app = _make_public_app(db_enabled=False)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/tasks", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_malformed_token_returns_401(self):
        with _jwt_patch():
            app = _make_public_app(db_enabled=False)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/tasks", headers={"Authorization": "Bearer not.a.token"})
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# Fix 3: GET /api/tasks filtered by user's device serials
# ═══════════════════════════════════════════════════════════════════════════════

class TestTasksFilteredByUser:

    @pytest.mark.anyio
    async def test_only_own_device_tasks_returned(self):
        """User sees only tasks targeting their devices."""
        tasks = [
            _FakeTask("t-mine", "serial-mine"),
            _FakeTask("t-other", "serial-other"),
        ]
        db_devices = [_FakeDevice("serial-mine", user_id="user-1")]
        with _jwt_patch(), _db_patch(db_devices):
            app = _make_public_app(db_enabled=True, queue=_mock_queue(tasks))
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/tasks", headers=_auth("user-1"))
        assert resp.status_code == 200
        ids = [t["id"] for t in resp.json()]
        assert "t-mine" in ids
        assert "t-other" not in ids

    @pytest.mark.anyio
    async def test_any_device_tasks_visible_to_all_authed_users(self):
        """Tasks with target=None (fleet / any-device) are shown to all authenticated users."""
        tasks = [
            _FakeTask("t-fleet", None, name="fleet:run-xyz"),
            _FakeTask("t-other", "serial-other"),
        ]
        db_devices = [_FakeDevice("serial-mine", user_id="user-1")]
        with _jwt_patch(), _db_patch(db_devices):
            app = _make_public_app(db_enabled=True, queue=_mock_queue(tasks))
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/tasks", headers=_auth("user-1"))
        ids = [t["id"] for t in resp.json()]
        assert "t-fleet" in ids       # target=None → visible
        assert "t-other" not in ids   # other user's device → hidden

    @pytest.mark.anyio
    async def test_user_with_no_devices_sees_only_fleet_tasks(self):
        """User with no assigned devices sees only target=None tasks."""
        tasks = [
            _FakeTask("t-fleet", None),
            _FakeTask("t-specific", "serial-someone-else"),
        ]
        with _jwt_patch(), _db_patch([]):  # user has no devices
            app = _make_public_app(db_enabled=True, queue=_mock_queue(tasks))
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/tasks", headers=_auth("user-1"))
        ids = [t["id"] for t in resp.json()]
        assert "t-fleet" in ids
        assert "t-specific" not in ids

    @pytest.mark.anyio
    async def test_multiple_owned_devices_all_shown(self):
        """All tasks for any of the user's devices are returned."""
        tasks = [
            _FakeTask("t-a", "serial-A"),
            _FakeTask("t-b", "serial-B"),
            _FakeTask("t-c", "serial-C"),  # belongs to someone else
        ]
        db_devices = [
            _FakeDevice("serial-A", user_id="user-1"),
            _FakeDevice("serial-B", user_id="user-1"),
            _FakeDevice("serial-C", user_id="user-2"),
        ]
        with _jwt_patch(), _db_patch(db_devices):
            app = _make_public_app(db_enabled=True, queue=_mock_queue(tasks))
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/tasks", headers=_auth("user-1"))
        ids = [t["id"] for t in resp.json()]
        assert "t-a" in ids
        assert "t-b" in ids
        assert "t-c" not in ids

    @pytest.mark.anyio
    async def test_ids_filter_applied_after_ownership_filter(self):
        """?ids= filter only operates on already-ownership-filtered tasks."""
        tasks = [
            _FakeTask("mine-1", "serial-mine"),
            _FakeTask("mine-2", "serial-mine"),
            _FakeTask("other-1", "serial-other"),
        ]
        db_devices = [_FakeDevice("serial-mine", user_id="user-1")]
        with _jwt_patch(), _db_patch(db_devices):
            app = _make_public_app(db_enabled=True, queue=_mock_queue(tasks))
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(
                    "/api/tasks?ids=mine-1,other-1",
                    headers=_auth("user-1"),
                )
        ids = [t["id"] for t in resp.json()]
        assert "mine-1" in ids
        assert "other-1" not in ids   # excluded by ownership before ids filter

    @pytest.mark.anyio
    async def test_two_users_see_different_task_sets(self):
        """Two users each see only their own device tasks."""
        tasks = [
            _FakeTask("t-u1", "serial-u1"),
            _FakeTask("t-u2", "serial-u2"),
        ]
        db_devices = [
            _FakeDevice("serial-u1", user_id="user-1"),
            _FakeDevice("serial-u2", user_id="user-2"),
        ]
        with _jwt_patch(), _db_patch(db_devices):
            app = _make_public_app(db_enabled=True, queue=_mock_queue(tasks))
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r1 = await ac.get("/api/tasks", headers=_auth("user-1"))
                r2 = await ac.get("/api/tasks", headers=_auth("user-2"))

        ids1 = [t["id"] for t in r1.json()]
        ids2 = [t["id"] for t in r2.json()]
        assert ids1 == ["t-u1"]
        assert ids2 == ["t-u2"]


# ═══════════════════════════════════════════════════════════════════════════════
# Fix 2: Device control routes check serial ownership
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeviceSerialOwnership:

    @pytest.mark.anyio
    async def test_own_device_returns_200(self):
        """Authenticated user can control their own device."""
        db_devices = [_FakeDevice("serial-mine", user_id="user-1")]
        with _jwt_patch(), _db_patch(db_devices):
            app = _make_device_control_app(db_enabled=True)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post("/tap/serial-mine", headers=_auth("user-1"))
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_other_users_device_returns_403(self):
        """User cannot control a device belonging to another user."""
        db_devices = [
            _FakeDevice("serial-u1", user_id="user-1"),
            _FakeDevice("serial-u2", user_id="user-2"),
        ]
        with _jwt_patch(), _db_patch(db_devices):
            app = _make_device_control_app(db_enabled=True)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post("/tap/serial-u2", headers=_auth("user-1"))
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_unknown_serial_returns_403(self):
        """Serial not in DB returns 403, not 404."""
        db_devices = [_FakeDevice("serial-mine", user_id="user-1")]
        with _jwt_patch(), _db_patch(db_devices):
            app = _make_device_control_app(db_enabled=True)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post("/tap/unknown-serial", headers=_auth("user-1"))
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_no_token_returns_401_before_ownership_check(self):
        """Missing token → 401 (auth failure before ownership check)."""
        app = _make_device_control_app(db_enabled=True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/tap/serial-mine")
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_lab_mode_no_auth_required(self):
        """db=False: no auth, no ownership check — lab behaviour unchanged."""
        app = _make_device_control_app(db_enabled=False)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/tap/any-serial")
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_invalid_token_returns_401(self):
        with _jwt_patch():
            app = _make_device_control_app(db_enabled=True)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post("/tap/s", headers={"Authorization": "Bearer bad.token"})
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_refresh_token_returns_401(self):
        token = _token(token_type="refresh")
        with _jwt_patch():
            app = _make_device_control_app(db_enabled=True)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post("/tap/s", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_user_can_access_multiple_own_devices(self):
        """User owning multiple devices can control all of them."""
        db_devices = [
            _FakeDevice("serial-A", user_id="user-1"),
            _FakeDevice("serial-B", user_id="user-1"),
        ]
        with _jwt_patch(), _db_patch(db_devices):
            app = _make_device_control_app(db_enabled=True)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r1 = await ac.post("/tap/serial-A", headers=_auth("user-1"))
                r2 = await ac.post("/tap/serial-B", headers=_auth("user-1"))
        assert r1.status_code == 200
        assert r2.status_code == 200

    @pytest.mark.anyio
    async def test_403_detail_mentions_authorized(self):
        """403 response body includes 'authorized' keyword."""
        db_devices = [_FakeDevice("serial-mine", user_id="user-1")]
        with _jwt_patch(), _db_patch(db_devices):
            app = _make_device_control_app(db_enabled=True)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post("/tap/not-mine", headers=_auth("user-1"))
        assert "authorized" in resp.json().get("detail", "").lower()
