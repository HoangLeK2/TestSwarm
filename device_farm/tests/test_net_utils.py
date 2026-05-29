"""Tests for LAN/Docker IP classification."""

from __future__ import annotations

from core.net_utils import (
    is_docker_internal_ip,
    is_private_ip,
    is_trusted_device_lan_ip,
)


def test_docker_gateway_not_trusted_device_ip():
    assert is_private_ip("172.19.0.1")
    assert is_docker_internal_ip("172.19.0.1")
    assert not is_trusted_device_lan_ip("172.19.0.1")


def test_real_lan_phone_ip_is_trusted():
    assert is_trusted_device_lan_ip("172.16.0.83")
    assert is_trusted_device_lan_ip("192.168.1.42")
    assert is_trusted_device_lan_ip("10.0.0.5")


def test_public_ip_not_trusted():
    assert not is_trusted_device_lan_ip("8.8.8.8")
