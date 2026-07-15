from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentBootPresence:
    reported: bool
    relay_id: str | None = None


def _append_unique(values: list[str], value: object) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def agent_boot_serial_candidates(device) -> list[str]:
    candidates: list[str] = []
    _append_unique(candidates, getattr(device, "serial", None))
    _append_unique(candidates, getattr(device, "device_serial", None))
    _append_unique(candidates, getattr(device, "adb_serial", None))
    _append_unique(candidates, getattr(device, "relay_serial", None))

    adb_ip = str(getattr(device, "adb_ip", "") or "").strip()
    if adb_ip:
        adb_port = int(getattr(device, "adb_port", 5555) or 5555)
        _append_unique(candidates, f"{adb_ip}:{adb_port}")
        _append_unique(candidates, adb_ip)
    return candidates


def device_requires_agent_boot(device) -> bool:
    return bool(
        str(getattr(device, "adb_serial", "") or "").strip()
        or str(getattr(device, "relay_serial", "") or "").strip()
        or str(getattr(device, "adb_ip", "") or "").strip()
    )


def control_conn_for_device(ctrl, device):
    if ctrl is None:
        return None
    for serial in agent_boot_serial_candidates(device):
        try:
            conn = ctrl.conn_for_serial(serial)
        except Exception:
            conn = None
        if conn is not None:
            return conn

    adb_ip = str(getattr(device, "adb_ip", "") or "").strip()
    if adb_ip:
        try:
            matched = ctrl.find_serial_by_ip(adb_ip)
        except Exception:
            matched = None
        if matched:
            try:
                return ctrl.conn_for_serial(matched)
            except Exception:
                return None
    return None


def agent_boot_presence_for_device(ctrl, device) -> AgentBootPresence:
    if ctrl is None or not device_requires_agent_boot(device):
        return AgentBootPresence(reported=False)
    conn = control_conn_for_device(ctrl, device)
    if conn is None:
        return AgentBootPresence(reported=False)
    return AgentBootPresence(
        reported=True,
        relay_id=str(getattr(conn, "relay_id", "") or "").strip() or None,
    )
