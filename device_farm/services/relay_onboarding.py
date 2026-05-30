from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import shlex
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from db import crud as repo
from db.database import AsyncSessionLocal


KIND_PROVISION = "provision"
KIND_CLAIM_CONNECT = "claim_connect"
TERMINAL_ITEM_STATUSES = {"ok", "failed", "skipped"}


class RelayOnboardingError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ClaimConnectOptions:
    connect: bool
    ws_base_url: str


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _truncate(value: str, limit: int = 1200) -> str:
    value = str(value or "")
    return value if len(value) <= limit else value[:limit] + "...[truncated]"


def _get_ctrl():
    from runtime.transports.agent_control_servicer import get_control_servicer

    svc = get_control_servicer()
    if svc is None:
        raise RuntimeError("control servicer not available")
    return svc


def _get_relay_manager():
    try:
        from runtime.transports.adb_relay_server import get_relay_manager

        return get_relay_manager()
    except Exception:
        return None


def get_live_caps(serial: str) -> dict:
    relay = _get_relay_manager()
    if relay is None:
        return {}
    try:
        return relay.get_capabilities(serial) or {}
    except Exception:
        return {}


def cap_display_name(serial: str, caps: dict | None) -> str:
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


# TEMP: set True to re-enable same-WiFi/LAN gate for relay device visibility & claim.
RELAY_SAME_WIFI_FILTER_ENABLED = False


def serial_is_same_lan(serial: str, relay_row, caps: dict | None = None) -> bool:
    if not RELAY_SAME_WIFI_FILTER_ENABLED:
        return True
    caps = caps if caps is not None else get_live_caps(serial)
    wlan_ip = str(caps.get("wlan_ip") or "").strip()
    wlan_cidr = str(caps.get("wlan_cidr") or "").strip()
    relay_ip = str(getattr(relay_row, "ip", "") or "").strip()
    if wlan_ip and relay_ip and _same_lan_ip(wlan_ip, relay_ip, wlan_cidr):
        return True
    if ":" in serial and relay_ip:
        serial_ip = serial.rsplit(":", 1)[0]
        if _same_lan_ip(serial_ip, relay_ip):
            return True
    return False


def device_serial_aliases(device) -> set[str]:
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


def find_matching_device(serial: str, devices: list):
    primary = next(
        (device for device in devices if str(getattr(device, "serial", "") or "").strip() == serial),
        None,
    )
    if primary is not None:
        return primary
    return next((device for device in devices if serial in device_serial_aliases(device)), None)


def serial_owned_by_other(serial: str, devices: list, user_id: str) -> bool:
    device = find_matching_device(serial, devices)
    owner = str(getattr(device, "user_id", "") or "") if device is not None else ""
    return bool(owner and owner != user_id)


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


async def resolve_visible_serials(
    db: AsyncSession,
    relay_row,
    *,
    user_id: str,
    mode: str,
    serials: list[str],
) -> list[str]:
    if not relay_row or getattr(relay_row, "status", "") != "online":
        raise RelayOnboardingError(404, "relay agent not online")

    reported = [str(s or "").strip() for s in list(getattr(relay_row, "serials", []) or [])]
    reported = [s for s in reported if s and not s.startswith("pending-")]
    reported_set = set(reported)
    requested = [str(s or "").strip() for s in serials if str(s or "").strip()]

    if mode == "selected":
        candidates = requested
        missing = [s for s in candidates if s not in reported_set]
        if missing:
            raise RelayOnboardingError(409, "serial is not reported by this relay agent")
    else:
        candidates = reported

    devices = await repo.list_devices_by_serial_aliases(db, _aliases_for_lookup(candidates))
    out: list[str] = []
    seen: set[str] = set()
    caps_by_serial: dict[str, dict] = {}
    for serial in candidates:
        if serial in seen:
            continue
        seen.add(serial)
        if serial_owned_by_other(serial, devices, user_id):
            continue
        caps_by_serial[serial] = get_live_caps(serial)
        if not serial_is_same_lan(serial, relay_row, caps_by_serial[serial]):
            continue
        out.append(serial)
    if not out:
        raise RelayOnboardingError(400, "no visible relay devices selected")
    return out


async def create_relay_batch_job(
    db: AsyncSession,
    relay_row,
    *,
    user_id: str,
    kind: str,
    mode: str,
    serials: list[str],
) -> object:
    visible = await resolve_visible_serials(db, relay_row, user_id=user_id, mode=mode, serials=serials)
    return await repo.create_relay_job(
        db,
        user_id=user_id,
        relay_id=relay_row.relay_id,
        kind=kind,
        serials=visible,
    )


async def claim_relay_serial(db: AsyncSession, relay_row, *, serial: str, user_id: str):
    serial = (serial or "").strip()
    if not serial or serial.startswith("pending-"):
        raise RelayOnboardingError(400, "invalid device serial")
    if serial not in set(relay_row.serials or []):
        raise RelayOnboardingError(409, "serial is not reported by this relay agent")

    caps = get_live_caps(serial)
    # TEMP: same-WiFi/LAN check disabled (RELAY_SAME_WIFI_FILTER_ENABLED=False).
    if RELAY_SAME_WIFI_FILTER_ENABLED and not serial_is_same_lan(serial, relay_row, caps):
        raise RelayOnboardingError(403, "device is not on the same WiFi/LAN as this relay agent")

    from db.crud.user import get_user_org_id
    from services.device_registration import DeviceRegistrationError, get_or_claim_device_for_user

    display_name = cap_display_name(serial, caps)
    org_id = await get_user_org_id(db, user_id)
    try:
        existing = await get_or_claim_device_for_user(
            db,
            serial=serial,
            display_name=display_name,
            user_id=user_id,
            org_id=org_id,
        )
    except DeviceRegistrationError as exc:
        raise RelayOnboardingError(exc.status_code, exc.detail) from exc

    db_serial = str(getattr(existing, "serial", "") or serial)
    if caps:
        await repo.update_device_metadata(
            db,
            db_serial,
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
    await repo.update_device_adb_identity(db, db_serial, adb_serial=serial)
    await db.flush()

    device = await repo.get_device_by_serial(db, db_serial)
    if not device:
        raise RelayOnboardingError(500, "device registration failed")
    return device


def build_device_agent_url(ws_base_url: str, device) -> str:
    return f"{ws_base_url.rstrip('/')}/device-agent?key={device.device_key}"


async def push_connect_url(ctrl, *, serial: str, ws_url: str) -> dict:
    cmd = (
        "am start "
        "-n jp.co.cyberagent.stf/.IdentityActivity "
        "-a android.intent.action.MAIN "
        f"--es qr_content {shlex.quote(ws_url)}"
    )
    return await ctrl.shell(serial, cmd, timeout=15.0)


async def _mark_remaining_failed(job_id: str, error: str) -> None:
    async with AsyncSessionLocal() as db:
        items = await repo.list_relay_job_items(db, job_id, limit=1000)
        for item in items:
            if item.status in TERMINAL_ITEM_STATUSES:
                continue
            await repo.finish_relay_job_item(
                db,
                item.id,
                status="failed",
                step=item.step or "dispatch",
                error=error,
                result={},
            )
        await repo.finish_relay_job(db, job_id)
        await db.commit()


async def run_relay_batch_job(job_id: str, *, claim_connect: Optional[ClaimConnectOptions] = None) -> None:
    prepared = await prepare_relay_batch_job(job_id)
    items = list(prepared.get("item_ids", []))
    if not items:
        await finish_relay_batch_job(job_id)
        return
    concurrency = int(prepared.get("concurrency", 1) or 1)
    sem = asyncio.Semaphore(concurrency)

    async def _run_item(item_id: str) -> None:
        async with sem:
            await run_relay_batch_item(job_id, item_id, claim_connect=claim_connect)

    await asyncio.gather(*[_run_item(item_id) for item_id in items])
    await finish_relay_batch_job(job_id)


def relay_job_concurrency(kind: str) -> int:
    if kind == KIND_PROVISION:
        return max(1, _env_int("RELAY_PROVISION_CONCURRENCY", 8))
    return max(1, _env_int("RELAY_CLAIM_CONNECT_CONCURRENCY", 12))


async def prepare_relay_batch_job(job_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        job = await repo.get_relay_job(db, job_id)
        if job is None:
            return {"job_id": job_id, "kind": "", "item_ids": [], "concurrency": 1}
        all_items = await repo.list_relay_job_items(db, job_id, limit=1000)
        items = [item for item in all_items if item.status not in TERMINAL_ITEM_STATUSES]
        await repo.mark_relay_job_running(db, job_id)
        await db.commit()
        return {
            "job_id": job_id,
            "kind": job.kind,
            "item_ids": [item.id for item in items],
            "concurrency": relay_job_concurrency(job.kind),
        }


async def run_relay_batch_item(
    job_id: str,
    item_id: str,
    *,
    claim_connect: Optional[ClaimConnectOptions] = None,
) -> None:
    try:
        ctrl = _get_ctrl()
    except Exception as exc:
        async with AsyncSessionLocal() as db:
            await repo.finish_relay_job_item(
                db,
                item_id,
                status="failed",
                step="dispatch",
                error=str(exc),
                result={},
            )
            await repo.recompute_relay_job_counts(db, job_id)
            await db.commit()
        return

    async with AsyncSessionLocal() as db:
        item = await repo.get_relay_job_item(db, item_id)
        job_row = await repo.get_relay_job(db, job_id)
        if item is None or job_row is None:
            return
        if item.status in TERMINAL_ITEM_STATUSES:
            return
        relay_row = await repo.get_relay_agent(db, job_row.relay_id, user_id=job_row.user_id)
        if relay_row is None or relay_row.status != "online":
            await repo.finish_relay_job_item(
                db,
                item.id,
                status="failed",
                step="relay",
                error="relay agent not online",
                result={},
            )
            await repo.recompute_relay_job_counts(db, job_id)
            await db.commit()
            return

        serial = item.serial
        try:
            if job_row.kind == KIND_PROVISION:
                await repo.mark_relay_job_item_running(db, item.id, step="bootstrap")
                await db.commit()
                res = await ctrl.bootstrap(serial, timeout=180.0)
                status = "ok" if res.get("ok") else "failed"
                output = str(res.get("output") or "")
                structured: dict = {}
                try:
                    parsed = json.loads(output)
                    if isinstance(parsed, dict):
                        structured = parsed
                except Exception:
                    structured = {}
                await repo.finish_relay_job_item(
                    db,
                    item.id,
                    status=status,
                    step="bootstrap",
                    error=_truncate(str(res.get("error") or "")),
                    result={
                        "ok": bool(res.get("ok")),
                        "exit_code": int(res.get("exit_code") or 0),
                        "output": _truncate(output),
                        **structured,
                    },
                )
            else:
                await repo.mark_relay_job_item_running(db, item.id, step="claim")
                device = await claim_relay_serial(db, relay_row, serial=serial, user_id=job_row.user_id)
                await db.commit()
                push_ok = False
                push_error = ""
                qr_url = ""
                if claim_connect and claim_connect.connect:
                    ws_url = build_device_agent_url(claim_connect.ws_base_url, device)
                    await repo.mark_relay_job_item_running(db, item.id, step="push_connect")
                    await db.commit()
                    res = await push_connect_url(ctrl, serial=serial, ws_url=ws_url)
                    push_ok = bool(res.get("ok"))
                    push_error = str(res.get("error") or "")
                    if not push_ok:
                        qr_url = ws_url
                else:
                    push_ok = True
                await repo.finish_relay_job_item(
                    db,
                    item.id,
                    status="ok" if push_ok else "failed",
                    step="push_connect" if claim_connect and claim_connect.connect else "claim",
                    device_id=device.id,
                    error=_truncate(push_error),
                    result={
                        "device_id": device.id,
                        "device_name": device.name,
                        "push_ok": push_ok,
                        "qr_url": qr_url,
                    },
                )
            await repo.recompute_relay_job_counts(db, job_id)
            await db.commit()
        except Exception as exc:
            await repo.finish_relay_job_item(
                db,
                item.id,
                status="failed",
                step=item.step or "run",
                error=_truncate(str(exc)),
                result={},
            )
            await repo.recompute_relay_job_counts(db, job_id)
            await db.commit()


async def finish_relay_batch_job(job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await repo.finish_relay_job(db, job_id)
        await db.commit()


def dispatch_local_relay_job(job_id: str, *, claim_connect: Optional[ClaimConnectOptions] = None) -> None:
    asyncio.create_task(run_relay_batch_job(job_id, claim_connect=claim_connect))


async def dispatch_temporal_relay_job(
    *,
    client,
    temporal_config,
    job_id: str,
    claim_connect: Optional[ClaimConnectOptions] = None,
) -> str:
    from temporal.relay_onboarding_workflows import RelayOnboardingWorkflow
    from temporal.shared import TASK_QUEUE_NAME

    task_queue = getattr(temporal_config, "task_queue", "") or TASK_QUEUE_NAME
    workflow_id = f"relay-onboarding-{job_id}"
    payload = {
        "job_id": job_id,
        "claim_connect": (
            {
                "connect": claim_connect.connect,
                "ws_base_url": claim_connect.ws_base_url,
            }
            if claim_connect is not None
            else None
        ),
    }
    await client.start_workflow(
        RelayOnboardingWorkflow.run,
        payload,
        id=workflow_id,
        task_queue=task_queue,
    )
    return workflow_id
