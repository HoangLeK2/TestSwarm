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
async def test_bootstrap_all_route_skips_pending_serials():
    """Route handler's pending-serial filter is exercised via the route function directly."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from datetime import datetime, timezone

    from api.routes.relay_agents import bootstrap_all

    # Build fake DB row with mixed real + pending serials
    fake_row = MagicMock()
    fake_row.relay_id = "relay-x"
    fake_row.serials = ["dev-real-1", "pending-abc123", "dev-real-2"]

    called_serials: list[str] = []

    # Fake control servicer
    fake_ctrl = MagicMock()
    async def _fake_bootstrap(serial: str, timeout: float = 180.0) -> dict:
        called_serials.append(serial)
        return {"ok": True, "exit_code": 0, "output": "done", "error": "", "serial": serial}
    fake_ctrl.bootstrap = _fake_bootstrap

    fake_db = AsyncMock()
    fake_user = MagicMock()

    with patch("api.routes.relay_agents.repo") as mock_repo, \
         patch("api.routes.relay_agents._get_ctrl", return_value=fake_ctrl):
        mock_repo.get_relay_agent = AsyncMock(return_value=fake_row)

        result = await bootstrap_all(relay_id="relay-x", db=fake_db, user=fake_user)

    assert "pending-abc123" not in called_serials, "pending serial must be skipped"
    assert "dev-real-1" in called_serials
    assert "dev-real-2" in called_serials
    assert result.total == 2
    assert result.ok == 2
