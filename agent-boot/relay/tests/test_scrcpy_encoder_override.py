"""
Tier 1 env override tests — per-serial and global encoder/codec pinning.

These live in the Phase 5 rollout: when a specific OEM (Vivo Android 16's
c2.qti.avc.encoder shows BAD_INDEX + param-skipped warnings in logcat) stalls,
ops flip an env var to force a different encoder without code redeploy.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from relay.scrcpy_relay import _per_serial_env


def test_per_serial_env_usb_serial():
    """USB serial like 10AE7S00HD002JK → env key appended verbatim."""
    with patch.dict("os.environ", {"SCRCPY_VIDEO_ENCODER__10AE7S00HD002JK": "OMX.qcom.video.encoder.avc"}, clear=False):
        assert _per_serial_env("SCRCPY_VIDEO_ENCODER", "10AE7S00HD002JK", "") == "OMX.qcom.video.encoder.avc"


def test_per_serial_env_tcp_serial_escaped():
    """TCP serial 192.168.1.42:5555 → colons & dots become underscores in env key."""
    with patch.dict("os.environ", {"SCRCPY_VIDEO_ENCODER__192_168_1_42_5555": "c2.android.avc.encoder"}, clear=False):
        assert _per_serial_env("SCRCPY_VIDEO_ENCODER", "192.168.1.42:5555", "") == "c2.android.avc.encoder"


def test_per_serial_env_falls_back_to_default():
    """Missing per-serial env → returns fallback."""
    with patch.dict("os.environ", {}, clear=True):
        assert _per_serial_env("SCRCPY_VIDEO_ENCODER", "10AE7S00HD002JK", "fallback-encoder") == "fallback-encoder"


def test_per_serial_env_empty_fallback():
    """Missing per-serial + empty fallback → empty string (signals no override)."""
    with patch.dict("os.environ", {}, clear=True):
        assert _per_serial_env("SCRCPY_VIDEO_ENCODER", "10AE7S00HD002JK", "") == ""


def test_per_serial_env_strips_whitespace():
    """Trailing whitespace in env value must be stripped — shell copy-paste safety."""
    with patch.dict("os.environ", {"SCRCPY_VIDEO_ENCODER__abc123": "  c2.qti.avc.encoder  "}, clear=False):
        assert _per_serial_env("SCRCPY_VIDEO_ENCODER", "abc123", "") == "c2.qti.avc.encoder"


def test_per_serial_overrides_default():
    """If both per-serial and default set, per-serial wins."""
    env = {
        "SCRCPY_VIDEO_ENCODER__abc123": "specific-encoder",
        "SCRCPY_VIDEO_ENCODER": "global-default",
    }
    with patch.dict("os.environ", env, clear=False):
        got = _per_serial_env("SCRCPY_VIDEO_ENCODER", "abc123", "global-default")
        assert got == "specific-encoder"
