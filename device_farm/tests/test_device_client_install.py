from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from runtime.core.device_client import DeviceClient


def _client(u2):
    client = DeviceClient.__new__(DeviceClient)
    client._u2 = u2
    client._u2_lock = threading.Lock()
    client._log = MagicMock()
    return client


def test_install_raises_when_u2_install_fails():
    u2 = MagicMock()
    u2.install.side_effect = RuntimeError("download failed")

    with pytest.raises(RuntimeError, match="download failed"):
        _client(u2).install("https://cdn.example/facebook.apk")


def test_install_raises_when_u2_unavailable():
    with pytest.raises(RuntimeError, match="no suitable transport"):
        _client(None).install("https://cdn.example/facebook.apk")
