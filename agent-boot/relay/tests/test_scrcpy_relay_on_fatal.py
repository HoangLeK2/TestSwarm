"""Regression tests for Phase 1 scrcpy stability fixes.

Focus: the on_fatal callback MUST fire exactly once when the relay loop exits
while _running is True, and MUST NOT fire on a clean stop().
"""
from __future__ import annotations

import asyncio
import select
import socket
import struct
from unittest.mock import patch

import pytest

import relay.scrcpy_relay as mod
from relay.scrcpy_relay import ScrcpyRelaySession


def _make_session(on_fatal) -> ScrcpyRelaySession:
    loop = asyncio.new_event_loop()
    return ScrcpyRelaySession(
        serial="test-serial",
        max_fps=30,
        max_width=800,
        enable_control=True,
        port=27183,
        send_queue=asyncio.Queue(),
        loop=loop,
        on_fatal=on_fatal,
    )


class _FakeSocket:
    def setsockopt(self, *_args, **_kwargs):
        return None

    def settimeout(self, *_args, **_kwargs):
        return None


def test_on_fatal_fires_once_on_budget_exhaustion():
    """Exhausting the retry budget must fire on_fatal exactly once."""
    fatal_calls: list[tuple[str, str]] = []
    session = _make_session(lambda s, r: fatal_calls.append((s, r)))

    # Every iteration raises; small budget + near-zero sleeps keep test fast.
    with patch.object(session, "_start_scrcpy_server"), \
         patch.object(session, "_connect_and_stream", side_effect=RuntimeError("frame timeout")), \
         patch.object(session, "_kill_server"), \
         patch.object(session, "_close_sockets"), \
         patch.object(mod, "_MAX_RECONNECTS", 2), \
         patch.object(mod, "_RECONNECT_BASE", 0.001), \
         patch.object(mod, "_RECONNECT_MAX", 0.001):
        session._running = True
        session._relay_loop()

    assert len(fatal_calls) == 1
    assert fatal_calls[0] == ("test-serial", "runtime_error")


def test_on_fatal_not_fired_on_clean_stop():
    """When stop() is called (running=False), on_fatal must NOT fire."""
    fatal_calls: list[tuple[str, str]] = []
    session = _make_session(lambda s, r: fatal_calls.append((s, r)))

    # First iteration does clean work then stop() is simulated by flipping
    # _running=False from inside the streaming mock. The loop should exit
    # the outer while via the _running condition — no error path.
    def stream_then_stop():
        session._running = False

    with patch.object(session, "_start_scrcpy_server"), \
         patch.object(session, "_connect_and_stream", side_effect=stream_then_stop), \
         patch.object(session, "_is_server_running", return_value=True):
        session._running = True
        session._relay_loop()

    assert fatal_calls == []


def test_config_packets_do_not_reset_no_frame_watchdog():
    fatal_calls: list[tuple[str, str]] = []
    session = _make_session(lambda s, r: fatal_calls.append((s, r)))
    session._enable_control_channel = False
    session._running = True

    cfg_header = struct.pack(">QI", mod._PTS_CONFIG_MASK, 4)
    calls = iter(
        [
            b"\x00",
            b"test-device".ljust(64, b"\x00"),
            struct.pack(">III", 0, 720, 1280),
            cfg_header,
            b"cfg!",
            socket.timeout(),
        ]
    )

    def fake_recvall(_sock, _n):
        value = next(calls)
        if isinstance(value, BaseException):
            raise value
        return value

    times = iter([0.0, 21.0])

    with patch.object(session, "_connect_with_retry", return_value=_FakeSocket()), \
         patch.object(mod, "_recvall", side_effect=fake_recvall), \
         patch.object(select, "select", return_value=([_FakeSocket()], [], [])), \
         patch.object(mod.time, "monotonic", side_effect=lambda: next(times)), \
         patch.object(mod, "_FRAME_TIMEOUT", 20.0):
        with pytest.raises(RuntimeError, match="frame timeout"):
            session._connect_and_stream()


def test_on_fatal_not_fired_on_keyboard_interrupt():
    """
    KeyboardInterrupt / SystemExit mean the interpreter is shutting down —
    the callback must NOT fire (otherwise we'd ask the farm to restart a
    session whose whole process is going away).
    """
    fatal_calls: list[tuple[str, str]] = []
    session = _make_session(lambda s, r: fatal_calls.append((s, r)))

    with patch.object(session, "_start_scrcpy_server", side_effect=KeyboardInterrupt("interrupt")):
        session._running = True
        with pytest.raises(KeyboardInterrupt):
            session._relay_loop()

    assert fatal_calls == []
