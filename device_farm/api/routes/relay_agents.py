from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, status

from api.deps import CurrentUser, DB
from api.schemas.relay_agent import BootstrapAllResult, RelayAgentOut
from db import crud as repo

router = APIRouter(prefix="/relay-agents", tags=["relay-agents"])


def _to_out(row) -> RelayAgentOut:
    return RelayAgentOut(
        relay_id          = row.relay_id,
        hostname          = row.hostname,
        ip                = row.ip,
        version           = row.version,
        serials           = list(row.serials or []),
        status            = row.status,
        connected_at      = row.connected_at,
        last_heartbeat_at = row.last_heartbeat_at,
        disconnected_at   = row.disconnected_at,
    )


def _get_ctrl():
    from runtime.transports.agent_control_servicer import get_control_servicer
    svc = get_control_servicer()
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="control servicer not available (gRPC not started)",
        )
    return svc


@router.get("", response_model=list[RelayAgentOut])
async def list_relay_agents(db: DB, user: CurrentUser):
    rows = await repo.list_relay_agents(db)
    return [_to_out(r) for r in rows]


@router.get("/{relay_id}", response_model=RelayAgentOut)
async def get_relay_agent(relay_id: str, db: DB, user: CurrentUser):
    row = await repo.get_relay_agent(db, relay_id)
    if not row:
        raise HTTPException(status_code=404, detail="relay agent not found")
    return _to_out(row)


@router.post("/{relay_id}/bootstrap-all", response_model=BootstrapAllResult)
async def bootstrap_all(relay_id: str, db: DB, user: CurrentUser):
    row = await repo.get_relay_agent(db, relay_id)
    if not row:
        raise HTTPException(status_code=404, detail="relay agent not found")

    ctrl = _get_ctrl()
    serials = [s for s in (row.serials or []) if not s.startswith("pending-")]

    sem = asyncio.Semaphore(4)

    async def _one(serial: str) -> dict:
        async with sem:
            r = await ctrl.bootstrap(serial, timeout=180.0)
            r["serial"] = serial
            return r

    results = await asyncio.gather(*[_one(s) for s in serials])
    ok_count = sum(1 for r in results if r.get("ok"))
    return BootstrapAllResult(
        relay_id = relay_id,
        total    = len(serials),
        ok       = ok_count,
        failed   = len(serials) - ok_count,
        results  = list(results),
    )
