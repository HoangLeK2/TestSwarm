from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import secrets
import shlex
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from typing import Optional

from pydantic import BaseModel, Field

from api.deps import CurrentUser, DB, require_permission
from api.org_scope import data_owner_user_id, device_visible_to_user
from api.schemas.device import DeviceOut
from api.schemas.relay_agent import (
    BootstrapAllResult,
    RelayDeviceConnectionOut,
    RelayAgentOut,
    RelayBatchJobCreate,
    RelayBatchJobItemOut,
    RelayBatchJobOut,
    RelayAgentTokenCreate,
    RelayAgentTokenCreated,
    RelayAgentTokenOut,
    RelayCommandOut,
)
from core.env import device_farm_ws_public_base
from db import crud as repo
from services import pairing as _pairing_mod
from services.device_registration import (
    DeviceRegistrationError,
    get_or_claim_device_for_user,
    http_exception_from_registration,
)
from services import relay_onboarding
from services.relay_onboarding import RELAY_SAME_WIFI_FILTER_ENABLED

router = APIRouter(prefix="/relay-agents", tags=["relay-agents"])
log = logging.getLogger(__name__)


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
        name=getattr(row, "name", "") or "",
        hostname=row.hostname,
        ip=row.ip,
        version=row.version,
        serials=list(row.serials or []),
        device_names={},
        status=row.status,
        live_connected=False,
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
    if not RELAY_SAME_WIFI_FILTER_ENABLED:
        return True
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


def _aliases_for_lookup(serials: list[str]) -> list[str]:
    aliases: set[str] = set()
    for serial in serials:
        serial = str(serial or "").strip()
        if not serial:
            continue
        aliases.add(serial)
        if ":" in serial:
            aliases.add(serial.rsplit(":", 1)[0])
    return list(aliases)


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


def _relay_host_key(row) -> tuple[str, str]:
    hostname = str(getattr(row, "hostname", "") or getattr(row, "relay_id", "") or "").strip().lower()
    ip = str(getattr(row, "ip", "") or "").strip()
    return hostname, ip


def _dedupe_relay_rows(rows: list) -> list:
    """Keep one row per host (hostname+ip): prefer online, then newest heartbeat."""
    best: dict[tuple[str, str], object] = {}
    for row in rows:
        key = _relay_host_key(row)
        if not key[0]:
            key = (str(getattr(row, "relay_id", "") or "").strip().lower(), key[1])
        prev = best.get(key)
        if prev is None:
            best[key] = row
            continue

        def _rank(r) -> tuple[int, float]:
            online = 1 if str(getattr(r, "status", "") or "") == "online" else 0
            hb = getattr(r, "last_heartbeat_at", None) or getattr(r, "connected_at", None)
            ts = hb.timestamp() if hb is not None else 0.0
            return online, ts

        if _rank(row) > _rank(prev):
            best[key] = row
    return list(best.values())


def _relay_to_out_same_wifi(
    row,
    owner_by_alias: dict[str, str],
    user_id: str,
    caps_by_serial: dict[str, dict],
) -> RelayAgentOut:
    out = _to_out(row)
    live_serials = _live_relay_serials(row.relay_id)
    out.live_connected = live_serials is not None
    if live_serials is None:
        out.status = "offline"
        out.serials = []
        out.device_names = {}
        return out

    names: dict[str, str] = {}
    visible_serials: list[str] = []
    for serial in sorted(live_serials):
        if serial.startswith("pending-"):
            continue
        caps = _cached_live_caps(serial, caps_by_serial)
        if _serial_is_same_wifi(serial, row, caps) and not _serial_owned_by_other_alias(serial, owner_by_alias, user_id):
            visible_serials.append(serial)
            names[serial] = _cap_display_name(serial, caps)

    out.serials = visible_serials
    out.device_names = {s: names.get(s, s) for s in visible_serials}
    return out


async def _attach_device_connection_state(
    db: DB,
    user: CurrentUser,
    agents: list[RelayAgentOut],
) -> list[RelayAgentOut]:
    serials = [serial for agent in agents for serial in agent.serials]
    if not serials:
        return agents

    devices = await repo.list_devices_by_serial_aliases(
        db, _aliases_for_lookup(serials)
    )
    visible_devices = [
        device
        for device in devices
        if await device_visible_to_user(db, user, device)
    ]
    active_device_ids = await repo.list_active_session_device_ids(
        db,
        [str(getattr(device, "id", "") or "") for device in visible_devices],
    )

    for agent in agents:
        connections: dict[str, RelayDeviceConnectionOut] = {}
        for serial in agent.serials:
            device = _find_matching_device(serial, visible_devices)
            if device is None:
                connections[serial] = RelayDeviceConnectionOut()
                continue
            device_id = str(getattr(device, "id", "") or "")
            connections[serial] = RelayDeviceConnectionOut(
                registered=True,
                device_id=device_id or None,
                device_agent_connected=bool(
                    device_id and device_id in active_device_ids
                ),
            )
        agent.device_connections = connections
    return agents


def _get_ctrl_optional():
    try:
        from runtime.transports.agent_control_servicer import get_control_servicer

        return get_control_servicer()
    except Exception:
        return None


def _get_relay_manager_optional():
    try:
        from runtime.transports.adb_relay_server import get_relay_manager

        return get_relay_manager()
    except Exception:
        return None


def _live_relay_serials(relay_id: str) -> set[str] | None:
    """Serials reported by the video relay channel, or None if stream relay is disconnected."""
    relay = _get_relay_manager_optional()
    if relay is None:
        return None
    relays = relay.registered_relays()
    if relay_id not in relays:
        return None

    svc = _get_ctrl_optional()
    ctrl_serials: set[str] | None = None
    if svc is not None:
        conn = svc.conn_for_relay(relay_id)
        if conn is not None:
            ctrl_serials = {str(s).strip() for s in conn.serials if str(s).strip()}

    video_serials = {str(s).strip() for s in relays.get(relay_id, []) if str(s).strip()}
    if ctrl_serials is not None:
        return video_serials & ctrl_serials
    return video_serials


def _get_ctrl():
    svc = _get_ctrl_optional()
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="control servicer not available (gRPC not started)",
        )
    return svc


def _schedule_bootstrap_for_registered_relay_device(serial: str) -> bool:
    """Fire-and-forget bootstrap after a user claims/registers a relay serial."""
    serial = (serial or "").strip()
    if not serial:
        return False
    ctrl = _get_ctrl_optional()
    if ctrl is None:
        log.info("relay bootstrap on register skipped serial=%s reason=no-control-servicer", serial)
        return False

    async def _run() -> None:
        try:
            result = await ctrl.bootstrap(serial, timeout=180.0)
            log.info(
                "relay bootstrap on register %s for %s",
                "ok" if result.get("ok") else "failed",
                serial,
            )
        except Exception as exc:
            log.warning("relay bootstrap on register error serial=%s: %s", serial, exc)

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        log.info("relay bootstrap on register skipped serial=%s reason=no-event-loop", serial)
        return False
    return True


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
        relay_serial=getattr(d, "relay_serial", None),
        managed_by_org_id=getattr(d, "managed_by_org_id", None),
        managed_by_relay_id=getattr(d, "managed_by_relay_id", None),
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


def _normalize_ws_base_url(raw: str) -> str | None:
    """Parse ws(s)://host[:port] (optional /device-agent suffix) for phone-facing URLs."""
    from urllib.parse import urlparse

    s = (raw or "").strip()
    if not s:
        return None
    if "/device-agent" in s:
        s = s.split("/device-agent", 1)[0].rstrip("/")
    lower = s.lower()
    if lower.startswith("ws://"):
        http_equiv = "http://" + s[5:]
        ws_scheme = "ws"
    elif lower.startswith("wss://"):
        http_equiv = "https://" + s[6:]
        ws_scheme = "wss"
    else:
        return None
    parsed = urlparse(http_equiv)
    if not parsed.hostname:
        return None
    netloc = parsed.netloc or parsed.hostname
    return f"{ws_scheme}://{netloc}"


def _ws_base_url_from_request(request: Request) -> str:
    configured = device_farm_ws_public_base()
    if configured:
        return configured
    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host", request.url.netloc)
    return f"{scheme}://{host}"


def _ws_base_for_push(request: Request, ws_base_url: str | None) -> str:
    """Prefer dashboard-provided LAN URL; fall back to server env / request host."""
    normalized = _normalize_ws_base_url(ws_base_url or "")
    if normalized:
        return normalized
    return _ws_base_url_from_request(request)


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


@router.get(
    "",
    response_model=list[RelayAgentOut],
    dependencies=[Depends(require_permission("relay-agents", "read"))],
)
async def list_relay_agents(db: DB, user: CurrentUser):
    org_id = getattr(user, "org_id", None)
    rows = _dedupe_relay_rows(await repo.list_relay_agents(db, org_id=org_id))
    caps_by_serial: dict[str, dict] = {}
    agents = [
        _relay_to_out_same_wifi(row, {}, user.id, caps_by_serial)
        for row in rows
    ]
    return await _attach_device_connection_state(db, user, agents)


@router.post(
    "/tokens",
    response_model=RelayAgentTokenCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("relay-agents", "create"))],
)
async def create_relay_agent_token(body: RelayAgentTokenCreate, db: DB, user: CurrentUser):
    raw_token, row = await repo.create_relay_agent_token(
        db,
        user_id=user.id,
        name=body.name,
        org_id=getattr(user, "org_id", None),
    )
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


@router.get(
    "/tokens",
    response_model=list[RelayAgentTokenOut],
    dependencies=[Depends(require_permission("relay-agents", "read"))],
)
async def list_relay_agent_tokens(db: DB, user: CurrentUser):
    return await repo.list_relay_agent_tokens(db, user_id=user.id)


@router.delete(
    "/tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("relay-agents", "delete"))],
)
async def revoke_relay_agent_token(token_id: str, db: DB, user: CurrentUser):
    ok = await repo.revoke_relay_agent_token(
        db, token_id=token_id, user_id=user.id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="relay agent token not found")
    await db.commit()
    return None


@router.post(
    "/{relay_id}/jobs/provision",
    response_model=RelayBatchJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission("relay-agents", "execute"))],
)
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


@router.post(
    "/{relay_id}/jobs/claim-connect",
    response_model=RelayBatchJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission("relay-agents", "execute"))],
)
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


@router.get(
    "/{relay_id}/jobs/{job_id}",
    response_model=RelayBatchJobOut,
    dependencies=[Depends(require_permission("relay-agents", "read"))],
)
async def get_relay_job(relay_id: str, job_id: str, db: DB, user: CurrentUser):
    job = await repo.get_relay_job(
        db, job_id, user_id=user.id, relay_id=relay_id
    )
    if job is None:
        raise HTTPException(status_code=404, detail="relay job not found")
    items = await repo.list_relay_job_items(db, job.id, limit=100)
    return _job_to_out(job, items)


@router.get(
    "/{relay_id}/jobs/{job_id}/items",
    response_model=list[RelayBatchJobItemOut],
    dependencies=[Depends(require_permission("relay-agents", "read"))],
)
async def list_relay_job_items(
    relay_id: str,
    job_id: str,
    db: DB,
    user: CurrentUser,
    item_status: str | None = Query(None, alias="status"),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    job = await repo.get_relay_job(
        db, job_id, user_id=user.id, relay_id=relay_id
    )
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


@router.get(
    "/{relay_id}",
    response_model=RelayAgentOut,
    dependencies=[Depends(require_permission("relay-agents", "read"))],
)
async def get_relay_agent(relay_id: str, db: DB, user: CurrentUser):
    row = await repo.get_relay_agent(
        db,
        relay_id,
        org_id=getattr(user, "org_id", None),
    )
    if not row:
        raise HTTPException(status_code=404, detail="relay agent not found")
    agents = [_relay_to_out_same_wifi(row, {}, user.id, {})]
    return (await _attach_device_connection_state(db, user, agents))[0]


async def _claim_relay_serial(db, row, serial: str, user) -> str:
    """Claim/update one reported serial. No commit, no bootstrap — the caller
    owns the transaction so a single register and a bulk register share exactly
    the same per-device work and cannot drift apart.

    Returns the canonical device serial. Raises DeviceRegistrationError /
    ValueError for the caller to map.
    """
    serial = (serial or "").strip()
    if not serial or serial.startswith("pending-"):
        raise ValueError("invalid device serial")
    if serial not in set(row.serials or []):
        raise ValueError("serial is not reported by this relay agent")

    caps = _get_live_caps(serial)
    display_name = _cap_display_name(serial, caps)
    existing = await get_or_claim_device_for_user(
        db,
        serial=serial,
        display_name=display_name,
        user_id=user.id,
        org_id=getattr(user, "org_id", None),
        allow_relay_reclaim=True,
    )
    if existing.managed_by_org_id is None:
        existing.managed_by_org_id = getattr(user, "org_id", None)
    existing.managed_by_relay_id = row.relay_id
    existing.relay_serial = serial
    canonical = str(getattr(existing, "serial", "") or serial)

    if caps:
        await repo.update_device_metadata(
            db,
            canonical,
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

    await repo.update_device_adb_identity(db, canonical, adb_serial=serial)

    # The device row now exists and this relay already reports the serial online
    # (checked above against row.serials), so advance the FSM to online here.
    # Without this the state stayed `unknown` until the agent happened to
    # re-emit its online transition — the relay bridge fires on that transition,
    # and if it arrived before the row existed it found nothing and gave up.
    # Registration is exactly the moment both facts are true, so it must not
    # depend on an agent restart to become usable.
    from services.device_state.relay_bridge import apply_relay_online

    try:
        await apply_relay_online(serial, db=db)
    except Exception as exc:
        log.warning("relay FSM online on register failed serial=%s: %s", serial, exc)

    return canonical


@router.post(
    "/{relay_id}/devices/{serial}/register",
    response_model=DeviceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("relay-agents", "create"))],
)
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

    try:
        canonical = await _claim_relay_serial(db, row, serial, user)
    except ValueError as exc:
        code = 409 if "not reported" in str(exc) else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    except DeviceRegistrationError as exc:
        raise http_exception_from_registration(exc) from exc

    await db.commit()

    device = await repo.get_device_by_serial(db, canonical)
    if not device:
        raise HTTPException(status_code=500, detail="device registration failed")
    _schedule_bootstrap_for_registered_relay_device((serial or "").strip())
    return _device_to_out(device, relay_id=relay_id)


class RegisterRelayDevicesBody(BaseModel):
    # Empty / omitted → register every serial the agent currently reports.
    serials: list[str] = Field(default_factory=list)


class RegisterRelayDeviceItemOut(BaseModel):
    serial: str
    status: str  # "registered" | "failed"
    device_id: Optional[str] = None
    name: Optional[str] = None
    message: Optional[str] = None


class RegisterRelayDevicesOut(BaseModel):
    results: list[RegisterRelayDeviceItemOut]


@router.post(
    "/{relay_id}/devices/register",
    response_model=RegisterRelayDevicesOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("relay-agents", "create"))],
)
async def register_relay_devices_bulk(
    relay_id: str,
    body: RegisterRelayDevicesBody,
    db: DB,
    user: CurrentUser,
):
    """Register several reported serials in one call.

    Partial success by design (same shape as DLQ bulk retry): one bad serial
    must not sink the rest, so each is committed on its own and reported
    individually. An empty `serials` list means "everything this agent reports".
    """
    row = await repo.get_relay_agent(db, relay_id, user_id=user.id)
    if not row or row.status != "online":
        raise HTTPException(status_code=404, detail="relay agent not online")

    reported = [str(s).strip() for s in (row.serials or []) if str(s).strip()]
    requested = [str(s).strip() for s in (body.serials or []) if str(s).strip()]
    targets = requested or reported

    results: list[RegisterRelayDeviceItemOut] = []
    to_bootstrap: list[str] = []

    for serial in targets:
        try:
            canonical = await _claim_relay_serial(db, row, serial, user)
            # Per-serial commit so a later failure cannot roll back an earlier
            # success — the whole point of a partial-success bulk.
            await db.commit()
        except (ValueError, DeviceRegistrationError) as exc:
            await db.rollback()
            results.append(
                RegisterRelayDeviceItemOut(serial=serial, status="failed", message=str(exc))
            )
            continue
        except Exception as exc:  # noqa: BLE001 — never let one device sink the batch
            await db.rollback()
            log.warning("bulk register serial=%s failed: %s", serial, exc)
            results.append(
                RegisterRelayDeviceItemOut(serial=serial, status="failed", message=str(exc))
            )
            continue

        device = await repo.get_device_by_serial(db, canonical)
        if not device:
            results.append(
                RegisterRelayDeviceItemOut(
                    serial=serial, status="failed", message="device lookup failed after claim"
                )
            )
            continue
        to_bootstrap.append(serial)
        results.append(
            RegisterRelayDeviceItemOut(
                serial=serial,
                status="registered",
                device_id=str(getattr(device, "id", "") or ""),
                name=str(getattr(device, "name", "") or ""),
            )
        )

    for serial in to_bootstrap:
        _schedule_bootstrap_for_registered_relay_device(serial)

    return RegisterRelayDevicesOut(results=results)


async def _resolve_relay_device_for_command(
    relay_id: str,
    serial: str,
    db: DB,
    user: CurrentUser,
    *,
    device_id: str | None = None,
):
    row = await repo.get_relay_agent(db, relay_id, user_id=user.id)
    if not row or row.status != "online":
        raise HTTPException(status_code=404, detail="relay agent not online")

    serial = (serial or "").strip()
    if serial not in set(row.serials or []):
        raise HTTPException(
            status_code=409, detail="serial is not reported by this relay agent"
        )

    all_devices = await repo.list_devices(db)
    device = None
    device_id_value = device_id.strip() if isinstance(device_id, str) else ""
    if device_id_value:
        device = await repo.get_device(db, device_id_value)
        if not await device_visible_to_user(db, user, device):
            raise HTTPException(status_code=404, detail="device not found")
        matched = _find_matching_device(serial, all_devices)
        if matched is not None and not await device_visible_to_user(db, user, matched):
            raise HTTPException(status_code=409, detail="serial already registered by another user")
    else:
        device = _find_matching_device(serial, all_devices)
        if not await device_visible_to_user(db, user, device):
            raise HTTPException(status_code=404, detail="registered device not found")

    if not str(getattr(device, "serial", "") or "").startswith("pending-") and not _serial_matches_device(serial, device):
        raise HTTPException(
            status_code=403,
            detail="relay serial does not belong to the selected device",
        )
    return row, device, serial


async def _push_connect_url_to_relay_device(
    relay_id: str,
    serial: str,
    request: Request,
    db: DB,
    user: CurrentUser,
    *,
    device_id: str | None = None,
    ws_base_url: str | None = None,
) -> RelayCommandOut:
    """Send the device-agent URL to STFService via agent-boot/ADB; no QR scan required."""
    _row, device, serial = await _resolve_relay_device_for_command(
        relay_id,
        serial,
        db,
        user,
        device_id=device_id,
    )

    ws_url = relay_onboarding.build_device_agent_url(
        _ws_base_for_push(
            request, ws_base_url if isinstance(ws_base_url, str) else None
        ),
        device,
    )
    log.info(
        "push-connect-url relay=%s serial=%s device_id=%s",
        relay_id,
        serial,
        getattr(device, "id", ""),
    )

    cmd = (
        "am start "
        "-n jp.co.cyberagent.stf/.IdentityActivity "
        "-a jp.co.cyberagent.stf.ACTION_IDENTIFY "
        "--activity-single-top "
        f"--es qr_content {shlex.quote(ws_url)}"
    )
    ctrl = _get_ctrl()
    res = await ctrl.shell(serial, cmd, timeout=15.0)
    return RelayCommandOut(**res)


@router.post(
    "/{relay_id}/devices/{serial}/push-connect-url",
    response_model=RelayCommandOut,
    dependencies=[Depends(require_permission("relay-agents", "execute"))],
)
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
    ws_base_url: str | None = Query(
        None,
        description="Phone-reachable ws(s) origin (same as dashboard QR). Overrides DEVICE_FARM_WS.",
    ),
):
    return await _push_connect_url_to_relay_device(
        relay_id,
        serial,
        request,
        db,
        user,
        device_id=device_id,
        ws_base_url=ws_base_url,
    )


@router.post(
    "/{relay_id}/devices/{serial}/connect",
    response_model=RelayCommandOut,
    dependencies=[Depends(require_permission("relay-agents", "execute"))],
)
async def connect_relay_device(
    relay_id: str,
    serial: str,
    request: Request,
    db: DB,
    user: CurrentUser,
    device_id: str | None = Query(
        None,
        description="Logical device id when DB serial is pending-* but ADB path serial is physical",
    ),
    ws_base_url: str | None = Query(
        None,
        description="Phone-reachable ws(s) origin (same as dashboard QR). Overrides DEVICE_FARM_WS.",
    ),
):
    return await _push_connect_url_to_relay_device(
        relay_id,
        serial,
        request,
        db,
        user,
        device_id=device_id,
        ws_base_url=ws_base_url,
    )


@router.post(
    "/{relay_id}/devices/{serial}/disconnect",
    response_model=RelayCommandOut,
    dependencies=[Depends(require_permission("relay-agents", "execute"))],
)
async def disconnect_relay_device(
    relay_id: str,
    serial: str,
    db: DB,
    user: CurrentUser,
    device_id: str | None = Query(
        None,
        description="Logical device id when DB serial is pending-* but ADB path serial is physical",
    ),
):
    _row, device, serial = await _resolve_relay_device_for_command(
        relay_id,
        serial,
        db,
        user,
        device_id=device_id,
    )
    ctrl = _get_ctrl()
    res = await ctrl.shell(
        serial, "am force-stop jp.co.cyberagent.stf", timeout=15.0
    )
    if res.get("ok"):
        await repo.close_active_sessions_for_device(
            db, str(getattr(device, "id", "") or "")
        )
        await db.commit()
    return RelayCommandOut(**res)


@router.post(
    "/{relay_id}/bootstrap-all",
    response_model=BootstrapAllResult,
    dependencies=[Depends(require_permission("relay-agents", "execute"))],
)
async def bootstrap_all(relay_id: str, db: DB, user: CurrentUser):
    row = await repo.get_relay_agent(db, relay_id, user_id=user.id)
    if not row:
        raise HTTPException(status_code=404, detail="relay agent not found")

    ctrl = _get_ctrl()
    user_devices = await repo.list_devices(
        db, org_id=getattr(user, "org_id", None), user_id=data_owner_user_id(user)
    )
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
