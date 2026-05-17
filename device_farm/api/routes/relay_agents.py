from __future__ import annotations

import asyncio
import ipaddress
import os
import secrets
import shlex
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from api.deps import CurrentUser, DB
from api.schemas.device import DeviceOut
from api.schemas.relay_agent import (
    BootstrapAllResult,
    RelayAgentOut,
    RelayBatchJobCreate,
    RelayBatchJobItemOut,
    RelayBatchJobOut,
    RelayAgentTokenCreate,
    RelayAgentTokenCreated,
    RelayAgentTokenOut,
    RelayCommandOut,
)
from db import crud as repo
from services import pairing as _pairing_mod
from services import relay_onboarding

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
        relay_id=row.relay_id,
        user_id=getattr(row, "user_id", None),
        enrollment_token_id=getattr(row, "enrollment_token_id", None),
        hostname=row.hostname,
        ip=row.ip,
        version=row.version,
        serials=list(row.serials or []),
        device_names={},
        status=row.status,
        connected_at=row.connected_at,
        last_heartbeat_at=row.last_heartbeat_at,
        disconnected_at=row.disconnected_at,
    )


def _cap_display_name(serial: str, caps: dict | None) -> str:
    caps = caps or {}
    return (
        str(caps.get("display_name") or "").strip()
        or str(caps.get("device_name") or "").strip()
        or str(caps.get("marketing_name") or "").strip()
        or " ".join(
            p
            for p in [
                str(caps.get("brand") or "").strip(),
                str(caps.get("model") or "").strip(),
            ]
            if p
        ).strip()
        or serial
    )


def _get_relay_manager():
    try:
        from runtime.transports.adb_relay_server import get_relay_manager

        return get_relay_manager()
    except Exception:
        return None


def _get_live_caps(serial: str) -> dict:
    relay = _get_relay_manager()
    if relay is None:
        return {}
    try:
        return relay.get_capabilities(serial) or {}
    except Exception:
        return {}


def _same_lan_ip(left: str, right: str, cidr: str = "") -> bool:
    try:
        l_ip = ipaddress.ip_address(str(left or "").split("%", 1)[0])
        r_ip = ipaddress.ip_address(str(right or "").split("%", 1)[0])
    except ValueError:
        return False
    if l_ip.version != r_ip.version or not l_ip.is_private or not r_ip.is_private:
        return False
    if cidr:
        try:
            return r_ip in ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            pass
    if l_ip.version == 4:
        return str(l_ip).split(".")[:3] == str(r_ip).split(".")[:3]
    return ipaddress.ip_network(f"{l_ip}/64", strict=False) == ipaddress.ip_network(f"{r_ip}/64", strict=False)


def _serial_is_same_wifi(serial: str, row, caps: dict | None = None) -> bool:
    caps = caps if caps is not None else _get_live_caps(serial)
    wlan_ip = str(caps.get("wlan_ip") or "").strip()
    wlan_cidr = str(caps.get("wlan_cidr") or "").strip()
    relay_ip = str(getattr(row, "ip", "") or "").strip()
    if wlan_ip and relay_ip and _same_lan_ip(wlan_ip, relay_ip, wlan_cidr):
        return True
    if ":" in serial and relay_ip:
        serial_ip = serial.rsplit(":", 1)[0]
        if _same_lan_ip(serial_ip, relay_ip):
            return True
    return False


def _device_serial_aliases(device) -> set[str]:
    aliases: set[str] = set()

    def _add(value: str | None) -> None:
        value = str(value or "").strip()
        if value:
            aliases.add(value)

    _add(getattr(device, "serial", None))
    _add(getattr(device, "adb_serial", None))
    adb_ip = str(getattr(device, "adb_ip", "") or "").strip()
    if adb_ip:
        adb_port = int(getattr(device, "adb_port", 5555) or 5555)
        _add(adb_ip)
        _add(f"{adb_ip}:{adb_port}")
    return aliases


def _serial_matches_device(serial: str, device) -> bool:
    return serial in _device_serial_aliases(device)


def _device_owner_aliases(devices: list) -> dict[str, str]:
    owners: dict[str, str] = {}
    for device in devices:
        owner = str(getattr(device, "user_id", "") or "")
        if not owner:
            continue
        for alias in _device_serial_aliases(device):
            owners.setdefault(alias, owner)
    return owners


def _find_matching_device(serial: str, devices: list):
    primary = next(
        (device for device in devices if str(getattr(device, "serial", "") or "").strip() == serial),
        None,
    )
    if primary is not None:
        return primary
    return next(
        (device for device in devices if _serial_matches_device(serial, device)),
        None,
    )


def _serial_owned_by_other(serial: str, devices: list, user_id: str) -> bool:
    device = _find_matching_device(serial, devices)
    owner = str(getattr(device, "user_id", "") or "") if device is not None else ""
    return bool(owner and owner != user_id)


def _serial_owned_by_other_alias(serial: str, owner_by_alias: dict[str, str], user_id: str) -> bool:
    owner = owner_by_alias.get(serial, "")
    return bool(owner and owner != user_id)


def _cached_live_caps(serial: str, caps_by_serial: dict[str, dict]) -> dict:
    if serial not in caps_by_serial:
        caps_by_serial[serial] = _get_live_caps(serial)
    return caps_by_serial[serial]


def _relay_to_out_same_wifi(
    row,
    owner_by_alias: dict[str, str],
    user_id: str,
    caps_by_serial: dict[str, dict],
) -> RelayAgentOut | None:
    names: dict[str, str] = {}
    visible_serials: list[str] = []
    for serial in list(row.serials or []):
        caps = _cached_live_caps(serial, caps_by_serial)
        if _serial_is_same_wifi(serial, row, caps) and not _serial_owned_by_other_alias(serial, owner_by_alias, user_id):
            visible_serials.append(serial)
            names[serial] = _cap_display_name(serial, caps)
    if not visible_serials:
        return None

    out = _to_out(row)
    out.serials = visible_serials
    out.device_names = {s: names.get(s, s) for s in visible_serials}
    return out


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


def _job_to_out(job, items: list | None = None) -> RelayBatchJobOut:
    return RelayBatchJobOut(
        id=job.id,
        relay_id=job.relay_id,
        kind=job.kind,
        status=job.status,
        total=job.total,
        ok=job.ok,
        failed=job.failed,
        pending=job.pending,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        updated_at=job.updated_at,
        items=[
            RelayBatchJobItemOut(
                id=item.id,
                serial=item.serial,
                device_id=item.device_id,
                status=item.status,
                step=item.step,
                attempts=item.attempts,
                error=item.error,
                result=item.result or {},
            )
            for item in (items or [])
        ],
    )


def _ws_base_url_from_request(request: Request) -> str:
    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host", request.url.netloc)
    return f"{scheme}://{host}"


def _raise_onboarding_error(exc: relay_onboarding.RelayOnboardingError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _relay_temporal_required() -> bool:
    raw = os.environ.get("RELAY_ONBOARDING_REQUIRE_TEMPORAL", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    env_name = os.environ.get("DEVICE_FARM_ENV", "").strip().lower()
    allow_local = os.environ.get("RELAY_ONBOARDING_ALLOW_LOCAL_FALLBACK", "").strip().lower()
    if allow_local in {"1", "true", "yes", "on"}:
        return False
    return env_name in {"prod", "production", "staging"}


async def _dispatch_relay_job(
    request: Request,
    db: DB,
    job,
    *,
    claim_connect: relay_onboarding.ClaimConnectOptions | None = None,
) -> None:
    scheduler = getattr(request.app.state, "scheduler", None)
    temporal_client = getattr(scheduler, "_client", None) if scheduler is not None else None
    temporal_cfg = getattr(scheduler, "_cfg", None) if scheduler is not None else None

    if temporal_client is None or temporal_cfg is None:
        if _relay_temporal_required():
            items = await repo.list_relay_job_items(db, job.id, limit=1000)
            for item in items:
                await repo.finish_relay_job_item(
                    db,
                    item.id,
                    status="failed",
                    step="temporal_dispatch",
                    error="Temporal is required for relay onboarding jobs",
                    result={},
                )
            await repo.finish_relay_job(db, job.id)
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Temporal is required for relay onboarding jobs",
            )
        relay_onboarding.dispatch_local_relay_job(job.id, claim_connect=claim_connect)
        return

    try:
        await relay_onboarding.dispatch_temporal_relay_job(
            client=temporal_client,
            temporal_config=temporal_cfg,
            job_id=job.id,
            claim_connect=claim_connect,
        )
    except Exception as exc:
        items = await repo.list_relay_job_items(db, job.id, limit=1000)
        for item in items:
            await repo.finish_relay_job_item(
                db,
                item.id,
                status="failed",
                step="temporal_dispatch",
                error=str(exc),
                result={},
            )
        await repo.finish_relay_job(db, job.id)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"failed to dispatch relay onboarding workflow: {exc}",
        )


@router.get("", response_model=list[RelayAgentOut])
async def list_relay_agents(db: DB, user: CurrentUser):
    rows = await repo.list_relay_agents(db, user_id=user.id)
    devices = await repo.list_devices(db)
    owner_by_alias = _device_owner_aliases(devices)
    caps_by_serial: dict[str, dict] = {}
    out: list[RelayAgentOut] = []
    for row in rows:
        item = _relay_to_out_same_wifi(row, owner_by_alias, user.id, caps_by_serial)
        if item is not None:
            out.append(item)
    return out


@router.post("/tokens", response_model=RelayAgentTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_relay_agent_token(body: RelayAgentTokenCreate, db: DB, user: CurrentUser):
    raw_token, row = await repo.create_relay_agent_token(db, user_id=user.id, name=body.name)
    await db.commit()
    return RelayAgentTokenCreated(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        status=row.status,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        token=raw_token,
    )


@router.get("/tokens", response_model=list[RelayAgentTokenOut])
async def list_relay_agent_tokens(db: DB, user: CurrentUser):
    return await repo.list_relay_agent_tokens(db, user_id=user.id)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_relay_agent_token(token_id: str, db: DB, user: CurrentUser):
    ok = await repo.revoke_relay_agent_token(db, token_id=token_id, user_id=user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="relay agent token not found")
    await db.commit()
    return None


@router.post("/{relay_id}/jobs/provision", response_model=RelayBatchJobOut, status_code=status.HTTP_202_ACCEPTED)
async def create_relay_provision_job(
    relay_id: str,
    body: RelayBatchJobCreate,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    row = await repo.get_relay_agent(db, relay_id, user_id=user.id)
    try:
        job = await relay_onboarding.create_relay_batch_job(
            db,
            row,
            user_id=user.id,
            kind=relay_onboarding.KIND_PROVISION,
            mode=body.mode,
            serials=body.serials,
        )
    except relay_onboarding.RelayOnboardingError as exc:
        _raise_onboarding_error(exc)
    await db.commit()
    await _dispatch_relay_job(request, db, job)
    return _job_to_out(job, await repo.list_relay_job_items(db, job.id, limit=100))


@router.post("/{relay_id}/jobs/claim-connect", response_model=RelayBatchJobOut, status_code=status.HTTP_202_ACCEPTED)
async def create_relay_claim_connect_job(
    relay_id: str,
    body: RelayBatchJobCreate,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    row = await repo.get_relay_agent(db, relay_id, user_id=user.id)
    try:
        job = await relay_onboarding.create_relay_batch_job(
            db,
            row,
            user_id=user.id,
            kind=relay_onboarding.KIND_CLAIM_CONNECT,
            mode=body.mode,
            serials=body.serials,
        )
    except relay_onboarding.RelayOnboardingError as exc:
        _raise_onboarding_error(exc)
    await db.commit()
    await _dispatch_relay_job(
        request,
        db,
        job,
        claim_connect=relay_onboarding.ClaimConnectOptions(
            connect=body.connect,
            ws_base_url=_ws_base_url_from_request(request),
        ),
    )
    return _job_to_out(job, await repo.list_relay_job_items(db, job.id, limit=100))


@router.get("/{relay_id}/jobs/{job_id}", response_model=RelayBatchJobOut)
async def get_relay_job(relay_id: str, job_id: str, db: DB, user: CurrentUser):
    job = await repo.get_relay_job(db, job_id, user_id=user.id, relay_id=relay_id)
    if job is None:
        raise HTTPException(status_code=404, detail="relay job not found")
    items = await repo.list_relay_job_items(db, job.id, limit=100)
    return _job_to_out(job, items)


@router.get("/{relay_id}/jobs/{job_id}/items", response_model=list[RelayBatchJobItemOut])
async def list_relay_job_items(
    relay_id: str,
    job_id: str,
    db: DB,
    user: CurrentUser,
    item_status: str | None = Query(None, alias="status"),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    job = await repo.get_relay_job(db, job_id, user_id=user.id, relay_id=relay_id)
    if job is None:
        raise HTTPException(status_code=404, detail="relay job not found")
    items = await repo.list_relay_job_items(db, job.id, status=item_status, limit=limit, offset=offset)
    return [
        RelayBatchJobItemOut(
            id=item.id,
            serial=item.serial,
            device_id=item.device_id,
            status=item.status,
            step=item.step,
            attempts=item.attempts,
            error=item.error,
            result=item.result or {},
        )
        for item in items
    ]


async def _relay_token_user_id_from_request(request: Request, db: DB) -> str:
    token = (
        request.headers.get("x-relay-enrollment-token")
        or request.headers.get("x-relay-agent-token")
        or ""
    ).strip()
    token_row = await repo.resolve_relay_agent_token(db, token)
    if token_row is None:
        raise HTTPException(status_code=403, detail="invalid relay enrollment token")
    return token_row.user_id


@router.get("/{relay_id}", response_model=RelayAgentOut)
async def get_relay_agent(relay_id: str, db: DB, user: CurrentUser):
    row = await repo.get_relay_agent(db, relay_id, user_id=user.id)
    if not row:
        raise HTTPException(status_code=404, detail="relay agent not found")
    devices = await repo.list_devices(db)
    owner_by_alias = _device_owner_aliases(devices)
    out = _relay_to_out_same_wifi(row, owner_by_alias, user.id, {})
    if out is None:
        raise HTTPException(status_code=404, detail="relay agent not found")
    return out


@router.post("/{relay_id}/devices/{serial}/register", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
async def register_relay_device(
    relay_id: str,
    serial: str,
    body: RegisterRelayDeviceBody,
    db: DB,
    user: CurrentUser,
):
    """Register/claim a device from an ADB serial currently reported by agent-boot."""
    row = await repo.get_relay_agent(db, relay_id, user_id=user.id)
    if not row or row.status != "online":
        raise HTTPException(status_code=404, detail="relay agent not online")

    serial = (serial or "").strip()
    if not serial or serial.startswith("pending-"):
        raise HTTPException(status_code=400, detail="invalid device serial")
    if serial not in set(row.serials or []):
        raise HTTPException(status_code=409, detail="serial is not reported by this relay agent")
    if not _serial_is_same_wifi(serial, row):
        raise HTTPException(status_code=403, detail="device is not on the same WiFi/LAN as this relay agent")

    all_devices = await repo.list_devices(db)
    existing = _find_matching_device(serial, all_devices)
    caps = _get_live_caps(serial)
    display_name = _cap_display_name(serial, caps)
    if existing:
        if existing.user_id and existing.user_id != user.id:
            raise HTTPException(status_code=409, detail="serial already registered by another user")
        if existing.user_id is None:
            await repo.assign_device_to_user(db, str(getattr(existing, "serial", "") or serial), user.id)
        if display_name and display_name != existing.name:
            await repo.update_device_name(db, existing.id, display_name)
    else:
        existing = await repo.create_device(db, serial, display_name, user.id)

    if caps:
        await repo.update_device_metadata(
            db,
            str(getattr(existing, "serial", "") or serial),
            brand=str(caps.get("brand") or ""),
            model=str(caps.get("model") or ""),
            android_version=str(caps.get("android_version") or ""),
            sdk_version=int(caps.get("sdk") or 0),
            screen_width=int(caps.get("screen_width") or 0),
            screen_height=int(caps.get("screen_height") or 0),
            adb_serial=serial,
            adb_ip=str(caps.get("wlan_ip") or "") or None,
            adb_port=5555,
        )

    await repo.update_device_adb_identity(db, str(getattr(existing, "serial", "") or serial), adb_serial=serial)
    await db.commit()

    device = await repo.get_device_by_serial(db, str(getattr(existing, "serial", "") or serial))
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
    row = await repo.get_relay_agent(db, relay_id, user_id=user.id)
    if not row or row.status != "online":
        raise HTTPException(status_code=404, detail="relay agent not online")

    serial = (serial or "").strip()
    if serial not in set(row.serials or []):
        raise HTTPException(status_code=409, detail="serial is not reported by this relay agent")
    if not _serial_is_same_wifi(serial, row):
        raise HTTPException(status_code=403, detail="device is not on the same WiFi/LAN as this relay agent")
    all_devices = await repo.list_devices(db)

    device = None
    if device_id and device_id.strip():
        device = await repo.get_device(db, device_id.strip())
        if not device or device.user_id != user.id:
            raise HTTPException(status_code=404, detail="device not found")
        matched = _find_matching_device(serial, all_devices)
        matched_owner = str(getattr(matched, "user_id", "") or "") if matched is not None else ""
        if matched_owner and matched_owner != user.id:
            raise HTTPException(status_code=409, detail="serial already registered by another user")
    else:
        device = _find_matching_device(serial, all_devices)
        if not device or device.user_id != user.id:
            raise HTTPException(status_code=404, detail="registered device not found")

    if not str(getattr(device, "serial", "") or "").startswith("pending-") and not _serial_matches_device(serial, device):
        raise HTTPException(
            status_code=403,
            detail="relay serial does not belong to the selected device",
        )

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
    row = await repo.get_relay_agent(db, relay_id, user_id=user.id)
    if not row:
        raise HTTPException(status_code=404, detail="relay agent not found")

    ctrl = _get_ctrl()
    user_devices = await repo.list_devices(db, user_id=user.id)
    user_serial_aliases = {
        alias
        for device in user_devices
        for alias in _device_serial_aliases(device)
    }
    serials = [
        s
        for s in (row.serials or [])
        if not s.startswith("pending-")
        and _serial_is_same_wifi(s, row)
        and s in user_serial_aliases
    ]

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
async def relay_pair_bulk(relay_id: str, body: PairBulkBody, request: Request, db: DB):
    """Create one pairing token per serial for a relay agent.

    Auth: X-Relay-Api-Key header (same key as gRPC).
    Returns {serial: ws_url} so agent can inject unique URLs per device.
    """
    _check_relay_key(request)
    user_id = await _relay_token_user_id_from_request(request, db)

    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host", request.url.netloc)

    pairings: dict[str, str] = {}
    for serial in body.serials:
        pairing_id = str(uuid.uuid4())
        _pairing_mod.store[pairing_id] = {
            "status":  "pending",
            "user_id": user_id,
            "device":  None,
            "relay_id": relay_id,
            "serial":   serial,
        }
        pairings[serial] = f"{scheme}://{host}/device-agent?pair={pairing_id}"

    return {"pairings": pairings}
