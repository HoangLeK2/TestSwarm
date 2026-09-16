
from __future__ import annotations

import logging
import shlex
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from api.deps import AdminUser, CurrentUser, DB, require_permission, require_permission_or_admin
from api.org_scope import data_owner_user_id, device_visible_to_user
from api.auth.rbac import build_enforcer_for_user_from_db, permission_domain
from runtime.core import DeviceManager
from api.schemas.device import (
    DeviceCreate,
    DeviceListOut,
    DeviceNameUpdate,
    DeviceOut,
    SessionOut,
)
from api.schemas.device_capacity import (
    CapacityGroupBreakdownOut,
    CapacityRelayBreakdownOut,
    CapacityReportOut,
    CapacityStateBreakdownOut,
    DeviceIdBreakdownOut,
)
from api.schemas.fleet_query import FleetDeviceItemOut, FleetDeviceListOut
from api.schemas.fleet_stats import (
    ActiveFleetSessionListOut,
    ActiveFleetSessionOut,
    FleetStatsFiltersOut,
    FleetStatsOut,
    SessionOwnerAnomalyOut,
    build_device_state_counts,
    build_session_owner_counts,
)
from api.schemas.relay_agent import RelayCommandOut
from api.schemas.device_group import UpdateTagsBody
from db import crud as repo
from db.crud.device_capacity import query_capacity_report, CapacityFilters
from db.crud.fleet_query import (
    FleetQueryFilters,
    FleetQueryNotFoundError,
    FleetQueryValidationError,
    query_fleet_devices,
)
from db.crud.fleet_stats import (
    FleetStatsNotFoundError,
    FleetStatsValidationError,
    query_fleet_stats,
)
from db.crud.device_group import update_device_tags
from db.crud.device_state import get_device_state, get_device_states_map
from db.models.enums import DeviceFsmState
from db.models.enums import McpSessionStatus
from db.models.device import Device
from db.models.device_fsm import DeviceFsmSnapshot
from db.models.mcp_session import McpSession
from core.env import device_farm_ws_public_base
from services.fleet_stats import derive_session_owner_type
from services import relay_onboarding
from services.device_allocation import claim_allocated_device, release_allocated_device
from services.device_state.exceptions import IllegalDeviceTransitionError
from services.device_state.service import ApplyOutcome, DeviceStateService
from services.agent_boot_presence import (
    AgentBootPresence,
    agent_boot_presence_for_device,
    device_requires_agent_boot,
)
from services import pairing as _pairing_mod
from tenancy.context import tenant_context
from web.metrics import fleet_stats_duration_seconds, fleet_stats_requests_total

log = logging.getLogger(__name__)

router = APIRouter(prefix="/devices", tags=["devices"])


def _direct_query_default(value):
    if value.__class__.__module__ == "fastapi.params" and getattr(value, "default", None) is None:
        return None
    return value


_ROOT_DIR = Path(__file__).resolve().parents[2]
_APK_CANDIDATES = [
    # Preferred: pre-bundled APK in device_farm/bundle/apks/STFService.apk
    _ROOT_DIR / "bundle" / "apks" / "STFService.apk",
    # Fallback: local Gradle release builds from ../STFService.apk Android project
    _ROOT_DIR.parent
    / "STFService.apk"
    / "app"
    / "build"
    / "outputs"
    / "apk"
    / "lite"
    / "release"
    / "app-lite-release.apk",
    _ROOT_DIR.parent
    / "STFService.apk"
    / "app"
    / "build"
    / "outputs"
    / "apk"
    / "full"
    / "release"
    / "app-full-release.apk",
    _ROOT_DIR.parent
    / "STFService.apk"
    / "app"
    / "build"
    / "outputs"
    / "apk"
    / "release"
    / "app-release.apk",
]


@router.get(
    "/stf-apk",
    summary="Download STFService APK",
    dependencies=[Depends(require_permission("devices", "read"))],
)
async def download_stf_apk():
    """
    Serve the STFService.apk used by Android devices.

    The file is resolved from a small set of well-known locations:
    - device_farm/bundle/apks/STFService.apk                (download_bundle.py output)
    - ../STFService.apk/app/build/outputs/apk/release/...   (local Gradle build)
    """
    for candidate in _APK_CANDIDATES:
        if candidate.is_file():
            return FileResponse(
                path=candidate,
                filename="STFService.apk",
                media_type="application/vnd.android.package-archive",
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="STFService.apk not found. Run download_bundle.py or build a release APK first.",
    )


# ── Đăng ký (chỉ tạo bản ghi, không kết nối điện thoại) ───────────────────────

class RegisterDeviceBody(BaseModel):
    name: str = ""
    description: str = ""  # ghi chú, lưu tạm vào name nếu backend chưa có cột riêng


class ManagedAgentConnectBody(BaseModel):
    wsBaseUrl: str | None = None


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


def _normalize_ws_base_url(raw: str) -> str | None:
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
    return f"{ws_scheme}://{parsed.netloc or parsed.hostname}"


def _ws_base_url_from_request(request: Request) -> str:
    configured = device_farm_ws_public_base()
    if configured:
        return configured
    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host", request.url.netloc)
    return f"{scheme}://{host}"


def _ws_base_for_managed_connect(request: Request, ws_base_url: str | None) -> str:
    return _normalize_ws_base_url(ws_base_url or "") or _ws_base_url_from_request(request)


class ConnectByIpBody(BaseModel):
    """Kết nối thiết bị qua ADB TCP: backend chủ động connect tới IP, không cần QR."""
    ip: str
    port: int = 5555


@router.post(
    "/connect-adb",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("devices", "execute"))],
)
async def connect_device_by_ip(request: Request, body: ConnectByIpBody, user: CurrentUser):
    """
    Backend chủ động kết nối tới thiết bị qua ADB over TCP.
    Thiết bị cần bật ADB over TCP (Wireless debugging hoặc adb tcpip 5555).
    Không cần QR: chỉ cần nhập IP và bấm Kết nối.
    """
    manager: DeviceManager = getattr(request.app.state, "manager", None)
    if not manager:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Device manager not available")
    ip = (body.ip or "").strip()
    if not ip:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="IP is required")
    port = max(1, min(65535, body.port))
    client = manager.register_adb_device(ip, port)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không kết nối được. Kiểm tra thiết bị cùng mạng, đã bật ADB over TCP (Wireless debugging hoặc adb tcpip 5555).",
        )
    return {"ok": True, "serial": client.serial}


@router.post(
    "/register",
    response_model=DeviceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("devices", "create"))],
)
async def register_device(body: RegisterDeviceBody, db: DB, user: CurrentUser):
    """
    Đăng ký thiết bị: chỉ tạo bản ghi (serial = pending-xxx), chưa kết nối điện thoại.
    Để kết nối điện thoại thật, user vào thẻ thiết bị → nhấn Kết nối → quét mã QR (key=device_key).
    """
    display_name = (body.name or "Thiết bị mới").strip()
    if body.description and body.description.strip():
        display_name = f"{display_name} — {body.description.strip()}"
    device = await repo.create_pending_device(
        db,
        user.id,
        display_name,
        org_id=getattr(user, "org_id", None),
    )
    await db.commit()
    return _to_out(device, state=DeviceFsmState.UNKNOWN.value)


@router.get(
    "/allocated",
    response_model=list[DeviceOut],
    dependencies=[Depends(require_permission("devices", "read"))],
)
async def list_allocated_devices(
    db: DB,
    user: CurrentUser,
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
):
    """List pool phones allocated to this workspace but not claimed by a user yet."""
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization context required")

    stmt = (
        select(Device)
        .where(Device.org_id == org_id)
        .where(Device.user_id.is_(None))
        .where(Device.managed_by_relay_id.isnot(None))
        .order_by(Device.created_at.asc())
        .limit(limit)
    )
    needle = (q or "").strip()
    if needle:
        pattern = f"%{needle}%"
        stmt = stmt.where(
            Device.serial.ilike(pattern)
            | Device.device_serial.ilike(pattern)
            | Device.adb_serial.ilike(pattern)
            | Device.relay_serial.ilike(pattern)
            | Device.name.ilike(pattern)
            | Device.brand.ilike(pattern)
            | Device.model.ilike(pattern)
        )

    rows = list((await db.execute(stmt)).scalars().all())
    states_map = await get_device_states_map(db, [device.id for device in rows])
    return [
        _to_out(
            device,
            relay_id=getattr(device, "managed_by_relay_id", None),
            state=states_map.get(device.id).state
            if states_map.get(device.id)
            else DeviceFsmState.UNKNOWN.value,
        )
        for device in rows
    ]


# ── Pairing (legacy / optional) ───────────────────────────────────────────────

class PairBulkBody(BaseModel):
    count: int = 1


@router.post(
    "/pair",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("devices", "create"))],
)
async def create_pairing(request: Request, user: CurrentUser):
 
    pairing_id = str(uuid.uuid4())
    _pairing_mod.store[pairing_id] = {
        "status":  "pending",
        "user_id": user.id,
        "device":  None,
    }
    scheme = "wss" if request.url.scheme == "https" else "ws"
    host   = request.headers.get("host", request.url.netloc)
    qr_url = f"{scheme}://{host}/device-agent?pair={pairing_id}"
    return {"pairing_id": pairing_id, "qr_url": qr_url}


@router.post(
    "/pair/bulk",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("devices", "create"))],
)
async def create_pairing_bulk(request: Request, body: PairBulkBody, user: CurrentUser):
    """
    Tạo nhiều pairing cùng lúc để kết nối nhiều thiết bị. Mỗi thiết bị dùng một URL (copy hoặc quét QR).
    """
    count = max(1, min(10, body.count))
    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host", request.url.netloc)
    pairings = []
    for _ in range(count):
        pairing_id = str(uuid.uuid4())
        _pairing_mod.store[pairing_id] = {
            "status": "pending",
            "user_id": user.id,
            "device": None,
        }
        qr_url = f"{scheme}://{host}/device-agent?pair={pairing_id}"
        pairings.append({"pairing_id": pairing_id, "qr_url": qr_url})
    return {"pairings": pairings}


@router.get(
    "/pair/{pairing_id}",
    dependencies=[Depends(require_permission("devices", "read"))],
)
async def poll_pairing(pairing_id: str, user: CurrentUser):
    """Poll until device connects and pairing is complete."""
    p = _pairing_mod.store.get(pairing_id)
    if not p or p.get("user_id") != user.id:
        raise HTTPException(status_code=404, detail="Pairing not found")
    return {"status": p["status"], "device": p.get("device")}


# ── Device CRUD ───────────────────────────────────────────────────────────────

@router.get(
    "",
    dependencies=[Depends(require_permission("devices", "read"))],
)
async def list_devices(
    request: Request,
    db: DB,
    user: CurrentUser,
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    state: str | None = Query(default=None),
    group_id: str | None = Query(default=None),
    owner_type: str | None = Query(default=None),
    relay_host: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    q: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    device_serial: str | None = Query(default=None),
    adb_serial: str | None = Query(default=None),
    relay_serial: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
):
    cursor = _direct_query_default(cursor)
    limit = _direct_query_default(limit)
    state = _direct_query_default(state)
    group_id = _direct_query_default(group_id)
    owner_type = _direct_query_default(owner_type)
    relay_host = _direct_query_default(relay_host)
    tag = _direct_query_default(tag)
    q = _direct_query_default(q)
    sort = _direct_query_default(sort)
    device_id = _direct_query_default(device_id)
    device_serial = _direct_query_default(device_serial)
    adb_serial = _direct_query_default(adb_serial)
    relay_serial = _direct_query_default(relay_serial)
    page = _direct_query_default(page)
    page_size = _direct_query_default(page_size)
    page_number = page

    org_id = getattr(user, "org_id", None)
    ctrl = _get_ctrl_servicer_optional()
    relay_manager = _get_relay_manager_optional()
    agent_boot_presence_cache: dict[str, AgentBootPresence] = {}

    def _presence_for(device):
        key = str(
            getattr(device, "id", None)
            or getattr(device, "db_id", None)
            or getattr(device, "serial", None)
            or getattr(device, "device_serial", None)
            or ""
        )
        if not key:
            return agent_boot_presence_for_device(ctrl, device)
        if key not in agent_boot_presence_cache:
            agent_boot_presence_cache[key] = agent_boot_presence_for_device(ctrl, device)
        return agent_boot_presence_cache[key]

    def _agent_boot_authoritative_state(device, current_state: str) -> str:
        if ctrl is None or not device_requires_agent_boot(device):
            return current_state
        if not _presence_for(device).reported:
            return DeviceFsmState.DEAD.value
        return current_state

    fleet_mode = any(
        value is not None
        for value in (
            cursor,
            limit,
            state,
            group_id,
            owner_type,
            relay_host,
            tag,
            q,
            sort,
            device_id,
            device_serial,
            adb_serial,
            relay_serial,
            page,
            page_size,
        )
    )
    if fleet_mode:
        if not org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization context required")
        try:
            fleet_page = await query_fleet_devices(
                db,
                filters=FleetQueryFilters(
                    org_id=org_id,
                    state=state,
                    group_id=group_id,
                    owner_type=owner_type,
                    relay_host=relay_host,
                    tag=tag,
                    q=q,
                    device_id=device_id,
                    device_serial=device_serial,
                    adb_serial=adb_serial,
                    relay_serial=relay_serial,
                ),
                limit=page_size or limit or 50,
                cursor=cursor,
                sort=sort or "-paired_at",
                offset=(page_number - 1) * (page_size or limit or 50) if page_number is not None else None,
            )
        except FleetQueryValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        except FleetQueryNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        log.info(
            "fleet_list org=%s total=%s limit=%s sort=%s state=%s group=%s q=%s",
            org_id,
            fleet_page.total,
            limit or 50,
            sort or "-paired_at",
            state,
            group_id,
            q,
        )
        if page_number is not None:
            devices_by_id = {
                str(device.id): device
                for device in await repo.list_devices(
                    db, org_id=org_id, user_id=data_owner_user_id(user)
                )
            }
            manager: DeviceManager | None = getattr(request.app.state, "manager", None)

            def resolve_relay_id(device) -> str | None:
                if ctrl is not None and not str(getattr(device, "serial", "")).startswith("pending-"):
                    presence = _presence_for(device)
                    if presence.relay_id:
                        return presence.relay_id
                    if device_requires_agent_boot(device):
                        return None
                if device_requires_agent_boot(device) or manager is None:
                    return None
                runtime_device = manager.get_device(getattr(device, "serial", ""))
                if runtime_device is None:
                    return None
                return None

            result_items: list[DeviceOut] = []
            for row in fleet_page.items:
                device = devices_by_id.get(row.db_id)
                if device is None:
                    continue
                effective_state = _agent_boot_authoritative_state(row, row.state)
                result_items.append(
                    _to_out(
                        device,
                        relay_id=resolve_relay_id(device),
                        adb_serial=row.adb_serial,
                        state=effective_state,
                        transport_online=_transport_online_for(
                            device, ctrl, relay_manager, adb_serial=row.adb_serial
                        ),
                    )
                )
            size = page_size or limit or 50
            return DeviceListOut(
                items=result_items,
                total=fleet_page.total,
                page=page_number,
                page_size=size,
                page_count=(fleet_page.total + size - 1) // size,
            )

        items: list[FleetDeviceItemOut] = []
        for row in fleet_page.items:
            effective_state = row.state if state else _agent_boot_authoritative_state(row, row.state)
            items.append(
                FleetDeviceItemOut(
                    db_id=row.db_id,
                    device_serial=row.device_serial,
                    adb_serial=row.adb_serial,
                    relay_serial=row.relay_serial,
                    adb_ip=row.adb_ip,
                    adb_port=row.adb_port,
                    name=row.name,
                    state=effective_state,
                    group_ids=row.group_ids,
                    current_session_id=row.current_session_id,
                    owner_type=row.owner_type,
                    owner_id=row.owner_id,
                    last_seen_at=row.last_seen_at,
                    model=row.model,
                    android_version=row.android_version,
                )
            )
        return FleetDeviceListOut(
            items=items,
            next_cursor=fleet_page.next_cursor,
            total=fleet_page.total,
        )

    devices = await repo.list_devices(
        db, org_id=org_id, user_id=data_owner_user_id(user)
    )
    manager: DeviceManager | None = getattr(request.app.state, "manager", None)

    def _resolve_relay_id(device) -> str | None:
        # Source of truth for relay-managed devices: agent-boot control channel.
        if ctrl is not None and not str(getattr(device, "serial", "")).startswith("pending-"):
            presence = _presence_for(device)
            if presence.relay_id:
                return presence.relay_id
            if device_requires_agent_boot(device):
                return None

        # Fallback for non relay-managed WS logical device view.
        if device_requires_agent_boot(device) or manager is None:
            return None
        runtime_device = manager.get_device(getattr(device, "serial", ""))
        if runtime_device is None:
            return None
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            if relay is None:
                return None

            adb_serial = str(getattr(runtime_device, "_adb_serial", "") or "")
            if adb_serial:
                conn = relay.relay_for_serial(adb_serial)
                if conn is not None:
                    return conn.relay_id
            return None
        except Exception:
            return None

    def _resolve_runtime_adb_serial(device) -> str | None:
        persisted = str(getattr(device, "adb_serial", "") or "").strip()
        if persisted:
            return persisted
        if manager is None:
            return None
        runtime_device = manager.get_device(getattr(device, "serial", ""))
        if runtime_device is None:
            return None
        adb_serial = str(getattr(runtime_device, "_adb_serial", "") or "").strip()
        return adb_serial or None

    states_map = await get_device_states_map(db, [d.id for d in devices])

    def _state_for(device, smap: dict) -> str:
        row = smap.get(device.id)
        state = row.state if row else DeviceFsmState.UNKNOWN.value
        return _agent_boot_authoritative_state(device, state)

    out = []
    for d in devices:
        d_state = _state_for(d, states_map)
        runtime_adb_serial = _resolve_runtime_adb_serial(d)
        out.append(
            _to_out(
                d,
                relay_id=_resolve_relay_id(d),
                adb_serial=runtime_adb_serial,
                state=d_state,
                transport_online=_transport_online_for(
                    d, ctrl, relay_manager, adb_serial=runtime_adb_serial
                ),
            )
        )
    return out


async def _can_view_owner_details(user, db) -> bool:
    if getattr(user, "role", None) == "admin":
        return True
    domain = permission_domain(user)
    enforcer = await build_enforcer_for_user_from_db(user, db, domain=domain)
    return bool(enforcer.enforce(str(user.id), domain, "devices", "manage"))


@router.get(
    "/capacity",
    response_model=CapacityReportOut,
    dependencies=[Depends(require_permission("devices", "read"))],
)
async def device_capacity_report(
    db: DB,
    user: CurrentUser,
    group_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    state: str | None = Query(default=None),
    relay_host: str | None = Query(default=None),
):
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization context required")
    try:
        report = await query_capacity_report(
            db,
            filters=CapacityFilters(
                organization_id=org_id,
                group_id=group_id,
                tag=tag,
                state=state,
                relay_host=relay_host,
            ),
        )
    except FleetStatsValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except FleetStatsNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    summary = report.summary
    log.info(
        "capacity_report org=%s scanned=%s latency_ms=%.1f group=%s tag=%s state=%s relay=%s",
        org_id,
        report.devices_scanned,
        report.latency_ms,
        group_id,
        tag,
        state,
        relay_host,
    )
    return CapacityReportOut(
        filters={
            "organization_id": org_id,
            "group_id": group_id,
            "tag": tag,
            "state": state,
            "relay_host": relay_host,
        },
        summary=CapacityStateBreakdownOut(**summary),
        by_state=report.by_state,
        by_group=[
            CapacityGroupBreakdownOut(
                group_id=row.group_id,
                total=row.total,
                available=row.available,
                busy=row.busy,
                dead=row.dead,
            )
            for row in report.by_group
        ],
        by_relay=[
            CapacityRelayBreakdownOut(
                relay_host=row.relay_host,
                total=row.total,
                available=row.available,
                busy=row.busy,
                dead=row.dead,
            )
            for row in report.by_relay
        ],
        sample_devices=[
            DeviceIdBreakdownOut(
                db_id=row.db_id,
                device_serial=row.device_serial,
                adb_serial=row.adb_serial,
                relay_serial=row.relay_serial,
            )
            for row in report.sample_devices
        ],
        devices_scanned=report.devices_scanned,
        latency_ms=report.latency_ms,
    )


@router.get(
    "/fleet/stats",
    response_model=FleetStatsOut,
    dependencies=[Depends(require_permission("devices", "read"))],
)
async def fleet_stats(
    db: DB,
    user: CurrentUser,
    group_id: str | None = Query(default=None),
    relay_host: str | None = Query(default=None),
):
    """Fleet health summary: device FSM counts and active sessions by owner type."""
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization context required")

    can_view_owner_details = await _can_view_owner_details(user, db)
    started = time.perf_counter()
    try:
        stats = await query_fleet_stats(
            db,
            org_id=org_id,
            group_id=group_id,
            relay_host=relay_host,
            include_owner_anomalies=can_view_owner_details,
        )
    except FleetStatsValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except FleetStatsNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    elapsed = time.perf_counter() - started
    try:
        fleet_stats_duration_seconds.observe(elapsed)
        fleet_stats_requests_total.labels(
            has_group_filter=str(bool(group_id)).lower(),
            has_relay_filter=str(bool(relay_host)).lower(),
        ).inc()
    except Exception:
        pass

    log.info(
        "fleet_stats org=%s group=%s relay=%s devices=%s sessions=%s latency_ms=%.1f",
        org_id,
        group_id,
        relay_host,
        stats.device_total,
        stats.active_session_total,
        elapsed * 1000,
    )

    owner_anomalies = None
    if can_view_owner_details:
        owner_anomalies = [
            SessionOwnerAnomalyOut(
                session_id=a.session_id,
                device_id=a.device_id,
                device_serial=a.device_serial,
                owner_type=a.owner_type,
                owner_id=a.owner_id,
                reason=a.reason,
            )
            for a in stats.owner_anomalies
        ]

    return FleetStatsOut(
        filters=FleetStatsFiltersOut(
            organization_id=stats.filters.organization_id,
            group_id=stats.filters.group_id,
            relay_host=stats.filters.relay_host,
        ),
        devices=build_device_state_counts(stats.devices_by_state),
        active_sessions=build_session_owner_counts(stats.active_sessions_by_owner),
        owner_anomalies=owner_anomalies,
    )


@router.get(
    "/fleet/sessions",
    response_model=ActiveFleetSessionListOut,
    dependencies=[Depends(require_permission("devices", "read"))],
)
async def list_active_fleet_sessions(
    db: DB,
    user: CurrentUser,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    """List active logical sessions so fleet totals are operator-auditable."""
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization context required",
        )

    scope = (
        Device.org_id == org_id,
        McpSession.status == McpSessionStatus.ACTIVE.value,
    )
    active_rows = (
        await db.execute(
            select(McpSession, Device)
            .join(Device, Device.serial == McpSession.device_serial)
            .where(*scope)
        )
    ).all()
    active_ids = {str(session.id) for session, _device in active_rows}
    busy_claim_rows = (
        await db.execute(
            select(DeviceFsmSnapshot, Device)
            .join(Device, Device.id == DeviceFsmSnapshot.device_id)
            .where(
                Device.org_id == org_id,
                DeviceFsmSnapshot.state == DeviceFsmState.BUSY.value,
                DeviceFsmSnapshot.session_id.is_not(None),
            )
        )
    ).all()

    sessions = [
        ActiveFleetSessionOut(
            session_id=session.id,
            device_id=device.id,
            device_serial=device.serial,
            device_name=device.name or device.serial,
            owner_type=derive_session_owner_type(
                session_id=session.id,
                user_id=session.user_id,
            ),
            source="active_session",
            created_at=session.created_at,
        )
        for session, device in active_rows
    ]
    sessions.extend(
        ActiveFleetSessionOut(
            session_id=str(snapshot.session_id),
            device_id=device.id,
            device_serial=device.serial,
            device_name=device.name or device.serial,
            owner_type=derive_session_owner_type(
                session_id=str(snapshot.session_id),
                user_id=None,
            ),
            source="busy_claim",
            created_at=snapshot.updated_at,
        )
        for snapshot, device in busy_claim_rows
        if str(snapshot.session_id) not in active_ids
    )
    serial_counts: dict[str, int] = {}
    for session in sessions:
        serial_counts[session.device_serial] = serial_counts.get(session.device_serial, 0) + 1
    sessions.sort(key=lambda session: session.created_at, reverse=True)
    for session in sessions:
        session.duplicate_for_device = serial_counts[session.device_serial] > 1

    return ActiveFleetSessionListOut(
        total=len(sessions),
        offset=offset,
        limit=limit,
        sessions=sessions[offset : offset + limit],
    )


@router.post(
    "",
    response_model=DeviceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("devices", "create"))],
)
async def create_device(body: DeviceCreate, db: DB, user: CurrentUser):
    """
    Đăng ký thiết bị thủ công bằng serial (dùng cho script/admin).
    Đăng ký từ UI phải qua POST /pair + quét mã QR, không dùng endpoint này.

    Semantics:
    - If no device with this serial exists: create and assign to current user.
    - If it exists without an owner (user_id is NULL): claim it for current user.
    - If it already belongs to current user: idempotent (optionally updates name).
    - If it belongs to another user: 409.
    """
    existing = await repo.get_device_by_serial(db, body.serial)
    if existing:
        # Already owned by another user → hard conflict
        if existing.org_id and existing.org_id != getattr(user, "org_id", None):
            raise HTTPException(
                status_code=409,
                detail="Serial already registered by another user",
            )

        # Unowned device created by agent / background flow → claim it
        if existing.user_id is None:
            await repo.assign_device_to_user(db, body.serial, user.id)
            try:
                existing.org_id = getattr(user, "org_id", None)
            except Exception:
                pass

        # For the same user, treat as idempotent and allow renaming
        if body.name and body.name != existing.name:
            await repo.update_device_name(db, existing.id, body.name)

        # existing object is still valid representation
        return _to_out(existing)

    device = await repo.create_device(
        db,
        body.serial,
        body.name,
        user.id,
        org_id=getattr(user, "org_id", None),
    )
    return _to_out(device)


# NOT "/claim": device_reserve.py owns POST /devices/{device_id}/claim (lease a
# session, body required) and is mounted first, so a claim here never reached
# this handler — the body-less call from the register dialog got that route's
# 422 instead. Same path, different verb in the domain sense; keep them apart.
@router.post(
    "/{device_id}/claim-allocated",
    response_model=DeviceOut,
    dependencies=[Depends(require_permission("devices", "create"))],
)
async def claim_allocated_device_route(
    device_id: str, request: Request, db: DB, user: CurrentUser
):
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=400, detail={"code": "WORKSPACE_SCOPE_REQUIRED"})
    device = await repo.get_device(db, device_id)
    if not device or device.org_id != org_id:
        raise HTTPException(status_code=404, detail={"code": "DEVICE_NOT_FOUND"})
    ip, ua = _client_meta(request)
    try:
        await claim_allocated_device(
            db,
            device,
            actor_user_id=user.id,
            org_id=org_id,
            ip_address=ip,
            user_agent=ua,
        )
    except ValueError as exc:
        code = str(exc)
        status_code = 409 if code == "DEVICE_ALREADY_REGISTERED" else 400
        raise HTTPException(status_code=status_code, detail={"code": code}) from exc
    await db.commit()
    state_row = await get_device_state(db, device.id)
    return _to_out(
        device,
        relay_id=getattr(device, "managed_by_relay_id", None),
        state=state_row.state if state_row else DeviceFsmState.UNKNOWN.value,
    )


@router.post(
    "/{device_id}/connect-via-managed-agent",
    response_model=RelayCommandOut,
    dependencies=[Depends(require_permission("devices", "execute"))],
)
async def connect_via_managed_agent(
    device_id: str,
    body: ManagedAgentConnectBody,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=400, detail={"code": "WORKSPACE_SCOPE_REQUIRED"})
    device = await repo.get_device(db, device_id)
    if not device or device.org_id != org_id:
        raise HTTPException(status_code=404, detail={"code": "DEVICE_NOT_FOUND"})
    if not device.user_id:
        raise HTTPException(status_code=409, detail={"code": "DEVICE_NOT_CLAIMED"})
    relay_id = str(getattr(device, "managed_by_relay_id", "") or "").strip()
    relay_serial = str(
        getattr(device, "relay_serial", None)
        or getattr(device, "adb_serial", None)
        or getattr(device, "serial", "")
        or ""
    ).strip()
    if not relay_id or not relay_serial:
        raise HTTPException(status_code=409, detail={"code": "MANAGED_AGENT_NOT_AVAILABLE"})
    managed_org_id = getattr(device, "managed_by_org_id", None) or org_id
    with tenant_context(str(managed_org_id)):
        relay = await repo.get_relay_agent(
            db,
            relay_id,
            org_id=managed_org_id,
        )
    if relay is None or relay.status != "online":
        raise HTTPException(status_code=404, detail={"code": "MANAGED_AGENT_OFFLINE"})
    if relay_serial not in set(relay.serials or []):
        raise HTTPException(status_code=409, detail={"code": "SERIAL_NOT_REPORTED_BY_AGENT"})

    ws_url = relay_onboarding.build_device_agent_url(
        _ws_base_for_managed_connect(request, body.wsBaseUrl),
        device,
    )
    cmd = (
        "am start "
        "-n jp.co.cyberagent.stf/.IdentityActivity "
        "-a jp.co.cyberagent.stf.ACTION_IDENTIFY "
        "--activity-single-top "
        f"--es qr_content {shlex.quote(ws_url)}"
    )
    ctrl = _get_ctrl_servicer_optional()
    if ctrl is None:
        raise HTTPException(status_code=503, detail={"code": "MANAGED_AGENT_CONTROL_UNAVAILABLE"})
    res = await ctrl.shell(relay_serial, cmd, timeout=15.0)
    return RelayCommandOut(**res)


@router.get(
    "/{device_id}",
    response_model=DeviceOut,
    dependencies=[Depends(require_permission("devices", "read"))],
)
async def get_device(device_id: str, db: DB, user: CurrentUser):
    device = await repo.get_device(db, device_id)
    if not device or device.org_id != getattr(user, "org_id", None):
        raise HTTPException(status_code=404, detail="Device not found")
    state_row = await get_device_state(db, device_id)
    state = state_row.state if state_row else DeviceFsmState.UNKNOWN.value
    return _to_out(device, state=state)


@router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("devices", "delete"))],
)
async def delete_device(device_id: str, db: DB, user: CurrentUser):
    """
    Xoá thiết bị của user hiện tại và mọi liên kết campaign-device.
    """
    device = await repo.get_device(db, device_id)
    if not device or device.org_id != getattr(user, "org_id", None):
        raise HTTPException(status_code=404, detail="Device not found")
    org_id = device.org_id
    state_row = await get_device_state(db, device_id)
    from_state = state_row.state if state_row else None
    session_id = state_row.session_id if state_row else None
    managed_by_org_id = getattr(device, "managed_by_org_id", None)
    if managed_by_org_id and managed_by_org_id != org_id:
        await release_allocated_device(
            db,
            device,
            actor_user_id=user.id,
            return_org_id=managed_by_org_id,
            action="device.released_by_workspace",
        )
    else:
        await repo.delete_device(db, device_id)
    await db.commit()
    try:
        from services.device_state.ws_publisher import publisher as lifecycle_publisher

        await lifecycle_publisher.publish_unpaired(
            device_id=device_id,
            organization_id=org_id,
            from_state=from_state,
            session_id=session_id,
        )
    except Exception as exc:
        log.debug("lifecycle unpaired publish skipped: %s", exc)
    return


@router.patch(
    "/{device_id}/tags",
    response_model=DeviceOut,
    dependencies=[Depends(require_permission("devices", "update"))],
)
async def update_tags(
    device_id: str, body: UpdateTagsBody, db: DB, user: CurrentUser
):
    device = await repo.get_device(db, device_id)
    if not device or device.org_id != getattr(user, "org_id", None):
        raise HTTPException(status_code=404, detail="Device not found")
    await update_device_tags(db, device_id, body.tags)
    await db.commit()
    device = await repo.get_device(db, device_id)
    return _to_out(device)


@router.patch(
    "/{device_id}/name",
    response_model=DeviceOut,
    dependencies=[Depends(require_permission("devices", "update"))],
)
async def update_name(
    device_id: str, body: DeviceNameUpdate, db: DB, user: CurrentUser
):
    device = await repo.get_device(db, device_id)
    if not device or device.org_id != getattr(user, "org_id", None):
        raise HTTPException(status_code=404, detail="Device not found")
    await repo.update_device_name(db, device_id, (body.name or "").strip())
    await db.commit()
    device = await repo.get_device(db, device_id)
    return _to_out(device)


@router.get(
    "/{device_id}/sessions",
    response_model=list[SessionOut],
    dependencies=[Depends(require_permission("devices", "read"))],
)
async def device_sessions(device_id: str, db: DB, user: CurrentUser):
    device = await repo.get_device(db, device_id)
    if not device or device.org_id != getattr(user, "org_id", None):
        raise HTTPException(status_code=404, detail="Device not found")
    sessions = await repo.list_sessions(db, device_id)
    return [
        SessionOut(
            id=s.id,
            client_ip=s.client_ip,
            connected_at=s.connected_at,
            disconnected_at=s.disconnected_at,
        )
        for s in sessions
    ]


# ── Relay control endpoints ───────────────────────────────────────────────────


def _get_ctrl_servicer_optional():
    from runtime.transports.agent_control_servicer import get_control_servicer

    return get_control_servicer()


def _get_relay_manager_optional():
    try:
        from runtime.transports.adb_relay_server import get_relay_manager

        return get_relay_manager()
    except Exception:
        return None


def _serial_reachable(ctrl, relay, serial: str) -> bool:
    if ctrl is not None and ctrl.conn_for_serial(serial):
        return True
    if relay is not None and relay.relay_for_serial(serial):
        return True
    return False


async def _resolve_relay_serial(
    db,
    device_id: str,
    user: CurrentUser,
    ctrl,
    relay,
    manager: DeviceManager | None = None,
) -> str:
    """Return a serial reachable on gRPC control and/or the video/WS relay."""
    device = await repo.get_device(db, device_id)
    if not hasattr(user, "id") and str(getattr(device, "user_id", "")) == str(user):
        visible = True
    else:
        visible = await device_visible_to_user(db, user, device)
    if not visible:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.serial.startswith("pending-"):
        raise HTTPException(status_code=409, detail="Device not yet paired")

    candidates: list[str] = []

    def _add_candidate(s: str | None) -> None:
        s = str(s or "").strip()
        if s and s not in candidates:
            candidates.append(s)

    _add_candidate(device.serial)
    _add_candidate(getattr(device, "adb_serial", None))
    if getattr(device, "adb_ip", None):
        _add_candidate(f"{device.adb_ip}:{getattr(device, 'adb_port', 5555)}")
        _add_candidate(device.adb_ip)

    if manager is not None:
        runtime_device = manager.get_device(device.serial)
        if runtime_device is not None:
            resolver = getattr(runtime_device, "_resolve_relay_serial", None)
            if callable(resolver):
                try:
                    _add_candidate(resolver())
                except Exception:
                    pass
            _add_candidate(getattr(runtime_device, "_adb_serial", None))

    for serial in candidates:
        if _serial_reachable(ctrl, relay, serial):
            return serial

    if relay is not None:
        for hint in candidates:
            resolved = relay.resolve_serial(hint)
            if resolved and _serial_reachable(ctrl, relay, resolved):
                return resolved

    if ctrl is not None:
        for hint in candidates:
            if "." in hint:
                ip = hint.split(":")[0]
                matched = ctrl.find_serial_by_ip(ip)
                if matched and _serial_reachable(ctrl, relay, matched):
                    return matched

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Device relay not connected (no control channel or video relay for this serial)",
    )


async def _dispatch_relay_command(
    db,
    device_id: str,
    user: CurrentUser,
    manager: DeviceManager | None,
    *,
    kind: str,
    timeout: float,
) -> RelayCommandOut:
    """Run bootstrap/restart via gRPC control plane, else video/WS relay queue."""
    ctrl = _get_ctrl_servicer_optional()
    relay = _get_relay_manager_optional()
    if ctrl is None and relay is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="relay transport not available",
        )

    serial = await _resolve_relay_serial(db, device_id, user, ctrl, relay, manager)

    if ctrl is not None and ctrl.conn_for_serial(serial):
        method = getattr(ctrl, kind)
        res = await method(serial, timeout=timeout)
        if res.get("ok") or res.get("error") != "no control channel for serial":
            return RelayCommandOut(**res)

    if relay is not None and relay.relay_for_serial(serial):
        relay_methods = {
            "bootstrap": lambda: relay.bootstrap(serial, timeout=timeout),
            "restart_u2": lambda: relay.restart_u2(serial, timeout=timeout),
            "restart_atx": lambda: relay.restart_atx(serial, timeout=timeout),
            "restart_scrcpy": lambda: relay.restart_scrcpy(serial, timeout=timeout),
        }
        fn = relay_methods.get(kind)
        if fn is None:
            raise HTTPException(status_code=500, detail=f"unknown relay command: {kind}")
        if kind == "restart_scrcpy":
            res = await fn()
            return RelayCommandOut(**res)
        ok = await fn()
        return RelayCommandOut(
            ok=ok,
            output="",
            exit_code=0 if ok else -1,
            error="" if ok else f"{kind} failed for serial {serial!r}",
        )

    if ctrl is not None:
        method = getattr(ctrl, kind)
        return RelayCommandOut(**(await method(serial, timeout=timeout)))

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Device relay not connected",
    )


class DeviceReviveOut(BaseModel):
    device_id: str
    from_state: str
    to_state: str
    actor: str


@router.post(
    "/{device_id}/revive",
    response_model=DeviceReviveOut,
    summary="Revive a DEAD device (admin)",
    dependencies=[Depends(require_permission_or_admin("devices", "manage"))],
)
async def revive_device(device_id: str, db: DB, admin: AdminUser):
    """Transition DEAD → CONNECTING after physical intervention (DF-T-02-005)."""
    device = await repo.get_device(db, device_id)
    org_id = getattr(admin, "org_id", None)
    if not device or device.org_id != org_id:
        raise HTTPException(status_code=404, detail="Device not found")

    svc = DeviceStateService()
    try:
        result = await svc.revive(
            db,
            device_id,
            actor=admin.id,
            device_serial=device.serial,
        )
    except IllegalDeviceTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if result.outcome != ApplyOutcome.APPLIED:
        raise HTTPException(
            status_code=409,
            detail=f"Revive not applied (outcome={result.outcome.value})",
        )
    return DeviceReviveOut(
        device_id=device_id,
        from_state=result.from_state.value if result.from_state else DeviceFsmState.DEAD.value,
        to_state=result.to_state.value if result.to_state else DeviceFsmState.CONNECTING.value,
        actor=admin.id,
    )


@router.post(
    "/{device_id}/bootstrap",
    response_model=RelayCommandOut,
    dependencies=[Depends(require_permission("devices", "execute"))],
)
async def bootstrap_device(device_id: str, request: Request, db: DB, user: CurrentUser):
    manager: DeviceManager | None = getattr(request.app.state, "manager", None)
    return await _dispatch_relay_command(
        db, device_id, user, manager, kind="bootstrap", timeout=180.0
    )


@router.post(
    "/{device_id}/restart-u2",
    response_model=RelayCommandOut,
    dependencies=[Depends(require_permission("devices", "execute"))],
)
async def restart_u2(device_id: str, request: Request, db: DB, user: CurrentUser):
    manager: DeviceManager | None = getattr(request.app.state, "manager", None)
    return await _dispatch_relay_command(
        db, device_id, user, manager, kind="restart_u2", timeout=60.0
    )


@router.post(
    "/{device_id}/restart-atx",
    response_model=RelayCommandOut,
    dependencies=[Depends(require_permission("devices", "execute"))],
)
async def restart_atx(device_id: str, request: Request, db: DB, user: CurrentUser):
    manager: DeviceManager | None = getattr(request.app.state, "manager", None)
    return await _dispatch_relay_command(
        db, device_id, user, manager, kind="restart_atx", timeout=30.0
    )


@router.post(
    "/{device_id}/restart-scrcpy",
    response_model=RelayCommandOut,
    dependencies=[Depends(require_permission("devices", "execute"))],
)
async def restart_scrcpy(device_id: str, request: Request, db: DB, user: CurrentUser):
    manager: DeviceManager | None = getattr(request.app.state, "manager", None)
    return await _dispatch_relay_command(
        db, device_id, user, manager, kind="restart_scrcpy", timeout=30.0
    )


def _device_serial_aliases(d, adb_serial: str | None = None) -> list[str]:
    """Every serial this device may be reachable under, deduped, order kept."""
    candidates = (
        adb_serial,
        getattr(d, "adb_serial", None),
        getattr(d, "relay_serial", None),
        getattr(d, "device_serial", None),
        getattr(d, "serial", None),
    )
    seen: list[str] = []
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def _transport_online_for(d, ctrl, relay, adb_serial: str | None = None) -> bool:
    """Live transport to this phone, whoever's agent carries it.

    Asks the control/video registries by serial instead of asking which agent
    the caller can see: the answer must not change because the agent belongs to
    the pool workspace rather than the tenant's.
    """
    return any(
        _serial_reachable(ctrl, relay, serial)
        for serial in _device_serial_aliases(d, adb_serial)
    )


def _to_out(
    d,
    *,
    relay_id: str | None = None,
    adb_serial: str | None = None,
    state: str = DeviceFsmState.UNKNOWN.value,
    transport_online: bool = False,
) -> DeviceOut:
    return DeviceOut(
        id=d.id,
        db_id=d.id,
        serial=d.serial,
        device_serial=getattr(d, "device_serial", None) or d.serial,
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
        adb_serial=adb_serial if adb_serial is not None else getattr(d, "adb_serial", None),
        relay_serial=getattr(d, "relay_serial", None),
        managed_by_org_id=getattr(d, "managed_by_org_id", None),
        managed_by_relay_id=getattr(d, "managed_by_relay_id", None),
        adb_ip=getattr(d, "adb_ip", None),
        adb_port=getattr(d, "adb_port", 5555),
        tags=getattr(d, "tags", "") or "",
        relay_id=relay_id if relay_id is not None else getattr(d, "managed_by_relay_id", None),
        transport_online=transport_online,
        state=state,
        status=getattr(d, "status", "paired") or "paired",
        paired_at=getattr(d, "paired_at", None),
        unpaired_at=getattr(d, "unpaired_at", None),
        notes=getattr(d, "notes", "") or "",
    )
