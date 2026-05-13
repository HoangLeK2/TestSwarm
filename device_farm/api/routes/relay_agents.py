from __future__ import annotations

import asyncio
import os
import secrets
import shlex
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from api.deps import CurrentUser, DB
from api.schemas.device import DeviceOut
from api.schemas.relay_agent import BootstrapAllResult, RelayAgentOut, RelayCommandOut
from db import crud as repo
from services import pairing as _pairing_mod

router = APIRouter(prefix="/relay-agents", tags=["relay-agents"])


def _check_relay_key(request: Request) -> None:
    """Validate X-Relay-Api-Key against RELAY_API_KEY env var."""
    expected = os.environ.get("RELAY_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="RELAY_API_KEY not configured on server")
    provided = request.headers.get("x-relay-api-key", "").strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid relay API key")


class PairBulkBody(BaseModel):
    serials: list[str]


class RegisterRelayDeviceBody(BaseModel):
    name: str = ""


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


def _device_to_out(d, *, relay_id: str | None = None) -> DeviceOut:
    return DeviceOut(
        id=d.id,
        serial=d.serial,
        name=d.name,
        device_key=d.device_key,
        user_id=d.user_id,
        brand=d.brand,
        model=d.model,
        android_version=d.android_version,
        sdk_version=d.sdk_version,
        screen_width=d.screen_width,
        screen_height=d.screen_height,
        last_seen=d.last_seen,
        created_at=d.created_at,
        adb_serial=getattr(d, "adb_serial", None),
        adb_ip=getattr(d, "adb_ip", None),
        adb_port=getattr(d, "adb_port", 5555),
        tags=getattr(d, "tags", "") or "",
        relay_id=relay_id,
    )


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


@router.post("/{relay_id}/devices/{serial}/register", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
async def register_relay_device(
    relay_id: str,
    serial: str,
    body: RegisterRelayDeviceBody,
    db: DB,
    user: CurrentUser,
):
    """Register/claim a device from an ADB serial currently reported by agent-boot."""
    row = await repo.get_relay_agent(db, relay_id)
    if not row or row.status != "online":
        raise HTTPException(status_code=404, detail="relay agent not online")

    serial = (serial or "").strip()
    if not serial or serial.startswith("pending-"):
        raise HTTPException(status_code=400, detail="invalid device serial")
    if serial not in set(row.serials or []):
        raise HTTPException(status_code=409, detail="serial is not reported by this relay agent")

    existing = await repo.get_device_by_serial(db, serial)
    name = (body.name or "").strip()
    if existing:
        if existing.user_id and existing.user_id != user.id:
            raise HTTPException(status_code=409, detail="serial already registered by another user")
        if existing.user_id is None:
            await repo.assign_device_to_user(db, serial, user.id)
        if name and name != existing.name:
            await repo.update_device_name(db, existing.id, name)
    else:
        await repo.create_device(db, serial, name or serial, user.id)

    await repo.update_device_adb_identity(db, serial, adb_serial=serial)
    await db.commit()

    device = await repo.get_device_by_serial(db, serial)
    if not device:
        raise HTTPException(status_code=500, detail="device registration failed")
    return _device_to_out(device, relay_id=relay_id)


@router.post("/{relay_id}/devices/{serial}/push-connect-url", response_model=RelayCommandOut)
async def push_connect_url_to_device(
    relay_id: str,
    serial: str,
    request: Request,
    db: DB,
    user: CurrentUser,
    device_id: str | None = Query(
        None,
        description="Logical device id when DB serial is pending-* but ADB path serial is physical",
    ),
):
    """Send the device-agent URL to STFService via agent-boot/ADB; no QR scan required."""
    row = await repo.get_relay_agent(db, relay_id)
    if not row or row.status != "online":
        raise HTTPException(status_code=404, detail="relay agent not online")

    serial = (serial or "").strip()
    if serial not in set(row.serials or []):
        raise HTTPException(status_code=409, detail="serial is not reported by this relay agent")

    device = None
    if device_id and device_id.strip():
        device = await repo.get_device(db, device_id.strip())
        if not device or device.user_id != user.id:
            raise HTTPException(status_code=404, detail="device not found")
    else:
        device = await repo.get_device_by_serial(db, serial)
        if not device or device.user_id != user.id:
            raise HTTPException(status_code=404, detail="registered device not found")

    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host", request.url.netloc)
    ws_url = f"{scheme}://{host}/device-agent?key={device.device_key}"

    cmd = (
        "am start "
        "-n jp.co.cyberagent.stf/.IdentityActivity "
        "-a android.intent.action.MAIN "
        f"--es qr_content {shlex.quote(ws_url)}"
    )
    ctrl = _get_ctrl()
    res = await ctrl.shell(serial, cmd, timeout=15.0)
    return RelayCommandOut(**res)


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


@router.post("/{relay_id}/pair-bulk", status_code=status.HTTP_200_OK)
async def relay_pair_bulk(relay_id: str, body: PairBulkBody, request: Request):
    """Create one pairing token per serial for a relay agent.

    Auth: X-Relay-Api-Key header (same key as gRPC).
    Returns {serial: ws_url} so agent can inject unique URLs per device.
    """
    _check_relay_key(request)

    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host", request.url.netloc)

    pairings: dict[str, str] = {}
    for serial in body.serials:
        pairing_id = str(uuid.uuid4())
        _pairing_mod.store[pairing_id] = {
            "status":  "pending",
            "user_id": None,
            "device":  None,
            "relay_id": relay_id,
            "serial":   serial,
        }
        pairings[serial] = f"{scheme}://{host}/device-agent?pair={pairing_id}"

    return {"pairings": pairings}
