"""Regression tests for Phase 1 scrcpy stability fixes.

Focus: the on_fatal callback MUST fire exactly once when the relay loop exits
while _running is True, and MUST NOT fire on a clean stop().
"""
from __future__ import annotations

import asyncio
import select
import socket
import struct
import threading
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


def test_streaming_health_requires_handshake_and_clears_with_sockets():
    session = _make_session(lambda _serial, _reason: None)
    session._relay_thread = threading.current_thread()

    assert session.is_streaming() is False

    session._stream_ready.set()
    assert session.is_streaming() is True

    session._close_sockets()
    assert session.is_streaming() is False


def test_stop_during_server_start_does_not_leave_late_scrcpy_server():
    """A stop racing _start_scrcpy_server must not let the old thread keep streaming."""
    fatal_calls: list[tuple[str, str]] = []
    session = _make_session(lambda s, r: fatal_calls.append((s, r)))
    start_entered = threading.Event()
    allow_start_return = threading.Event()
    connect_calls = 0
    kill_calls = 0

    def slow_start_server():
        start_entered.set()
        assert allow_start_return.wait(timeout=2.0)

    def connect_and_stream():
        nonlocal connect_calls
        connect_calls += 1

    def kill_server():
        nonlocal kill_calls
        kill_calls += 1

    with patch.object(session, "_start_scrcpy_server", side_effect=slow_start_server), \
         patch.object(session, "_connect_and_stream", side_effect=connect_and_stream), \
         patch.object(session, "_kill_server", side_effect=kill_server), \
         patch.object(session, "_close_sockets"), \
         patch.object(mod, "_adb", return_value=("", 0)):
        session._running = True
        relay_thread = threading.Thread(target=session._relay_loop, daemon=True)
        session._relay_thread = relay_thread
        relay_thread.start()
        assert start_entered.wait(timeout=2.0)

        allow_start_return.set()
        session.stop()

    relay_thread.join(timeout=1.0)
    assert not relay_thread.is_alive()
    assert connect_calls == 0
    assert kill_calls >= 2
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


def test_idle_after_first_video_frame_does_not_auto_request_idr():
    fatal_calls: list[tuple[str, str]] = []
    session = _make_session(lambda s, r: fatal_calls.append((s, r)))
    session._enable_control_channel = False
    session._running = True

    video_data = b"\x00\x00\x00\x01\x65idr"
    video_header = struct.pack(">QI", 1, len(video_data))
    calls = iter(
        [
            b"\x00",
            b"test-device".ljust(64, b"\x00"),
            struct.pack(">III", 0, 720, 1280),
            video_header,
            video_data,
            socket.timeout(),
            RuntimeError("stop"),
        ]
    )

    def fake_recvall(_sock, _n):
        value = next(calls)
        if isinstance(value, BaseException):
            raise value
        return value

    times = iter([0.0, 1.0])
    idr_requests = 0

    def fake_request_idr():
        nonlocal idr_requests
        idr_requests += 1

    with patch.object(session, "_connect_with_retry", return_value=_FakeSocket()), \
         patch.object(mod, "_recvall", side_effect=fake_recvall), \
         patch.object(select, "select", return_value=([_FakeSocket()], [], [])), \
         patch.object(mod.time, "monotonic", side_effect=lambda: next(times, 2.0)), \
         patch.object(session, "_request_idr", side_effect=fake_request_idr):
        with pytest.raises(RuntimeError, match="stop"):
            session._connect_and_stream()

    assert idr_requests == 0


def test_idr_recovery_after_first_video_frame_times_out_if_no_frame_returns():
    fatal_calls: list[tuple[str, str]] = []
    session = _make_session(lambda s, r: fatal_calls.append((s, r)))
    session._enable_control_channel = False
    session._running = True

    video_data = b"\x00\x00\x00\x01\x65idr"
    video_header = struct.pack(">QI", 1, len(video_data))
    calls = iter(
        [
            b"\x00",
            b"test-device".ljust(64, b"\x00"),
            struct.pack(">III", 0, 720, 1280),
            video_header,
            video_data,
            socket.timeout(),
            socket.timeout(),
        ]
    )

    def fake_recvall(_sock, _n):
        value = next(calls)
        if value == video_data:
            session._need_idr = True
        if isinstance(value, BaseException):
            raise value
        return value

    times = iter([0.0, 1.0, 2.0, 3.0, 10.0])
    idr_requests = 0

    def fake_request_idr():
        nonlocal idr_requests
        idr_requests += 1

    with patch.object(session, "_connect_with_retry", return_value=_FakeSocket()), \
         patch.object(mod, "_recvall", side_effect=fake_recvall), \
         patch.object(select, "select", return_value=([_FakeSocket()], [], [])), \
         patch.object(mod.time, "monotonic", side_effect=lambda: next(times, 9.0)), \
         patch.object(mod, "_FRAME_TIMEOUT", 5.0), \
         patch.object(mod, "_IDR_REQUEST_MIN_GAP", 1.0), \
         patch.object(session, "_request_idr", side_effect=fake_request_idr):
        with pytest.raises(RuntimeError, match="frame timeout after IDR"):
            session._connect_and_stream()

    assert idr_requests >= 1


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
