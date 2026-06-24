"""LAN/Docker-aware IP helpers for device routing."""

from __future__ import annotations

import ipaddress


_DOCKER_BRIDGE_NETS = tuple(
    ipaddress.ip_network(f"172.{octet}.0.0/16") for octet in range(17, 32)
)
# Docker Desktop (macOS/Windows) host-gateway seen as WS client IP from containers.
_DOCKER_DESKTOP_HOST_NETS = (
    ipaddress.ip_network("192.168.65.0/24"),
)


def is_private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address((host or "").strip())
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local)
    except Exception:
        return False


def is_docker_internal_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address((host or "").strip())
        return any(ip in net for net in _DOCKER_BRIDGE_NETS)
    except Exception:
        return False


def is_docker_desktop_host_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address((host or "").strip())
        return any(ip in net for net in _DOCKER_DESKTOP_HOST_NETS)
    except Exception:
        return False


def is_trusted_device_lan_ip(host: str) -> bool:
    return (
        is_private_ip(host)
        and not is_docker_internal_ip(host)
        and not is_docker_desktop_host_ip(host)
    )
