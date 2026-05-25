"""Tests for u2_executor app / file batch ops."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from relay.u2_executor import _op_app_start, _op_app_stop, _op_app_clear, _op_push_file


def test_op_app_start_with_activity():
    dev = MagicMock()
    _op_app_start(dev, {
        "package": "com.example",
        "activity": ".MainActivity",
        "stop_before": True,
        "use_monkey": False,
    })
    dev.app_start.assert_called_once_with(
        "com.example", ".MainActivity", stop=True, use_monkey=False
    )


def test_op_app_stop():
    dev = MagicMock()
    _op_app_stop(dev, {"package": "com.example"})
    dev.app_stop.assert_called_once_with("com.example")


def test_op_app_clear():
    dev = MagicMock()
    _op_app_clear(dev, {"package": "com.example"})
    dev.app_clear.assert_called_once_with("com.example")


def test_op_push_file_with_mode():
    dev = MagicMock()
    _op_push_file(dev, {
        "local_path": "/tmp/a.txt",
        "remote_path": "/sdcard/a.txt",
        "mode": 0o755,
    })
    dev.push.assert_called_once_with("/tmp/a.txt", "/sdcard/a.txt", mode=0o755)
