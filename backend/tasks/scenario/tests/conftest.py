"""Shared fixtures for scenario unit tests."""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def mock_device():
    """Minimal DeviceClient mock — no real ADB connection needed."""
    d = MagicMock()
    d.serial = "test_serial"
    d.screen_width = 1080
    d.screen_height = 1920
    d.u2 = MagicMock()
    d.hierarchy_xml.return_value = "<hierarchy></hierarchy>"
    d.take_screenshot.return_value = None
    d.tap = MagicMock()
    return d


@pytest.fixture
def mock_u2():
    u2 = MagicMock()
    u2.find_element.return_value = None
    return u2


@pytest.fixture
def cancel_event():
    return threading.Event()
