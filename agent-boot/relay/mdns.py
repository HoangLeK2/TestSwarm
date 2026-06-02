"""
relay/mdns.py — Android 11+ Wireless Debugging auto-discovery via mDNS (zeroconf).

When a device has Wireless Debugging ON, it broadcasts _adb-tls-connect._tcp.
We listen and run `adb connect ip:port` automatically — no manual IP entry needed.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from relay.adb import _adb_connect

logger = logging.getLogger("relay.mdns")

try:
    from zeroconf import ServiceBrowser, Zeroconf  # type: ignore
    _ZEROCONF_OK = True
except ImportError:
    _ZEROCONF_OK = False

_ADB_MDNS_SERVICE = "_adb-tls-connect._tcp.local."


def _mdns_enabled() -> bool:
    return os.getenv("AGENT_BOOT_MDNS", "").strip().lower() in {"1", "true", "yes", "on"}


class _AdbMdnsListener:
    def __init__(self) -> None:
        self._connected: set[str] = set()

    def add_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if not info:
            return
        for addr in info.parsed_addresses():
            ip_port = f"{addr}:{info.port}"
            if ip_port in self._connected:
                continue
            self._connected.add(ip_port)
            output, rc = _adb_connect(ip_port)
            if rc == 0:
                logger.info("mDNS: auto-connected %s — %s", ip_port, output)
            else:
                logger.debug("mDNS: connect %s failed — %s", ip_port, output)

    def remove_service(self, _zc: "Zeroconf", _type: str, _name: str) -> None:
        pass  # AdbDeviceWatcher handles offline via track-devices

    def update_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
        self.add_service(zc, type_, name)


def start_mdns_discovery() -> Optional["Zeroconf"]:
    """Start mDNS listener when AGENT_BOOT_MDNS=1. Returns Zeroconf or None."""
    if not _mdns_enabled():
        logger.debug("mDNS discovery disabled (set AGENT_BOOT_MDNS=1 to enable)")
        return None
    if not _ZEROCONF_OK:
        logger.debug("zeroconf not installed — mDNS discovery disabled (uv add zeroconf)")
        return None
    zc = Zeroconf()
    ServiceBrowser(zc, _ADB_MDNS_SERVICE, _AdbMdnsListener())
    logger.info("mDNS discovery started (%s)", _ADB_MDNS_SERVICE)
    return zc
