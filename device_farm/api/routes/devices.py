
from __future__ import annotations

import uuid
from pathlib import Path

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from api.deps import CurrentUser, DB
from runtime.core import DeviceManager
from api.schemas.device import DeviceCreate, DeviceOut, SessionOut
from api.schemas.device_group import UpdateTagsBody
from db import crud as repo
from db.crud.device_group import update_device_tags
from services import pairing as _pairing_mod

router = APIRouter(prefix="/devices", tags=["devices"])


_ROOT_DIR = Path(__file__).resolve().parents[2]
_APK_CANDIDATES = [
    # Preferred: pre-bundled APK in device_farm/bundle/apks/STFService.apk
    _ROOT_DIR / "bundle" / "apks" / "STFService.apk",
    # Fallback: local Gradle release build from ../STFService.apk Android project
    _ROOT_DIR.parent
    / "STFService.apk"
    / "app"
    / "build"
    / "outputs"
    / "apk"
    / "release"
    / "app-release.apk",
]


@router.get("/stf-apk", summary="Download STFService APK")
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


class ConnectByIpBody(BaseModel):
    """Kết nối thiết bị qua ADB TCP: backend chủ động connect tới IP, không cần QR."""
    ip: str
    port: int = 5555


@router.post("/connect-adb", status_code=status.HTTP_200_OK)
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


@router.post("/register", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
async def register_device(body: RegisterDeviceBody, db: DB, user: CurrentUser):
    """
    Đăng ký thiết bị: chỉ tạo bản ghi (serial = pending-xxx), chưa kết nối điện thoại.
    Để kết nối điện thoại thật, user vào thẻ thiết bị → nhấn Kết nối → quét mã QR (key=device_key).
    """
    display_name = (body.name or "Thiết bị mới").strip()
    if body.description and body.description.strip():
        display_name = f"{display_name} — {body.description.strip()}"
    device = await repo.create_pending_device(db, user.id, display_name)
    await db.commit()
    return _to_out(device)


# ── Pairing (legacy / optional) ───────────────────────────────────────────────

class PairBulkBody(BaseModel):
    count: int = 1


@router.post("/pair", status_code=status.HTTP_201_CREATED)
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


@router.post("/pair/bulk", status_code=status.HTTP_201_CREATED)
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


@router.get("/pair/{pairing_id}")
async def poll_pairing(pairing_id: str, user: CurrentUser):
    """Poll until device connects and pairing is complete."""
    p = _pairing_mod.store.get(pairing_id)
    if not p or p.get("user_id") != user.id:
        raise HTTPException(status_code=404, detail="Pairing not found")
    return {"status": p["status"], "device": p.get("device")}


# ── Device CRUD ───────────────────────────────────────────────────────────────

@router.get("", response_model=list[DeviceOut])
async def list_devices(db: DB, user: CurrentUser):
    devices = await repo.list_devices(db, user_id=user.id)
    return [_to_out(d) for d in devices]


@router.post("", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
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
        if existing.user_id and existing.user_id != user.id:
            raise HTTPException(
                status_code=409,
                detail="Serial already registered by another user",
            )

        # Unowned device created by agent / background flow → claim it
        if existing.user_id is None:
            await repo.assign_device_to_user(db, body.serial, user.id)

        # For the same user, treat as idempotent and allow renaming
        if body.name and body.name != existing.name:
            await repo.update_device_name(db, existing.id, body.name)

        # existing object is still valid representation
        return _to_out(existing)

    device = await repo.create_device(db, body.serial, body.name, user.id)
    return _to_out(device)


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(device_id: str, db: DB, user: CurrentUser):
    device = await repo.get_device(db, device_id)
    if not device or device.user_id != user.id:
        raise HTTPException(status_code=404, detail="Device not found")
    return _to_out(device)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(device_id: str, db: DB, user: CurrentUser):
    """
    Xoá thiết bị của user hiện tại và mọi liên kết campaign-device.
    """
    device = await repo.get_device(db, device_id)
    if not device or device.user_id != user.id:
        raise HTTPException(status_code=404, detail="Device not found")
    await repo.delete_device(db, device_id)
    await db.commit()
    return


@router.patch("/{device_id}/tags", response_model=DeviceOut)
async def update_tags(
    device_id: str, body: UpdateTagsBody, db: DB, user: CurrentUser
):
    device = await repo.get_device(db, device_id)
    if not device or device.user_id != user.id:
        raise HTTPException(status_code=404, detail="Device not found")
    await update_device_tags(db, device_id, body.tags)
    await db.commit()
    device = await repo.get_device(db, device_id)
    return _to_out(device)


@router.get("/{device_id}/sessions", response_model=list[SessionOut])
async def device_sessions(device_id: str, db: DB, user: CurrentUser):
    device = await repo.get_device(db, device_id)
    if not device or device.user_id != user.id:
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


def _to_out(d) -> DeviceOut:
    return DeviceOut(
        id=d.id, serial=d.serial, name=d.name,
        device_key=d.device_key, user_id=d.user_id,
        brand=d.brand, model=d.model,
        android_version=d.android_version, sdk_version=d.sdk_version,
        screen_width=d.screen_width, screen_height=d.screen_height,
        last_seen=d.last_seen, created_at=d.created_at,
        adb_ip=getattr(d, "adb_ip", None),
        adb_port=getattr(d, "adb_port", 5555),
        tags=getattr(d, "tags", "") or "",
    )
