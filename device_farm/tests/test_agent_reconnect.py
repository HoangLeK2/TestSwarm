"""
tests/test_agent_reconnect.py — unit tests for the agent-reconnect race condition.

Race scenario:
  The new agent WS handler calls attach_agent_sender() + on_agent_ready() BEFORE
  the old handler's finally-block runs on_agent_disconnected().  Without guards,
  on_agent_disconnected() from the old session would:
    - overwrite _agent_send with None
    - stop the NEW tunnels
    - null _u2 (already pointing at new port)
    - set state → DISCONNECTED

Two fixes applied:
  1. on_agent_disconnected(sender=...) — skips teardown when _agent_send ≠ sender
  2. attach_agent_sender() — resets _tunnels_ready_channels + nulls _u2 so that
     on_agent_ready() correctly sees is_initial=True for the new session even when
     on_agent_disconnected() was a no-op (stale-sender guard fired).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional
from unittest.mock import MagicMock, call, patch

import pytest

from core.config import Config
from runtime.core.device_client import DeviceClient, DeviceState


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_device(serial: str = "test-serial") -> DeviceClient:
    d = DeviceClient(serial=serial, index=0, config=Config())
    d._state = DeviceState.READY
    return d


def _make_send(name: str = "send") -> MagicMock:
    return MagicMock(name=name)


def _attach(device: DeviceClient,
            send: Optional[MagicMock] = None,
            channels: Optional[set] = None,
            u2_port: int = 9000) -> MagicMock:
    """
    Simulate attach_agent_sender() + on_agent_ready(): install sender,
    tunnels, u2 client, and ready channels.
    """
    if send is None:
        send = _make_send()

    # Patch TunnelSet so attach_agent_sender() doesn't open real sockets
    mock_tunnels = MagicMock(name="tunnels")
    mock_tunnels.start_all.return_value = {
        "u2": u2_port, "stfservice": u2_port + 1
    }
    with patch("runtime.core.device_client.TunnelSet", return_value=mock_tunnels):
        device.attach_agent_sender(send)

    # Manually set ready state (mimics on_agent_ready → _setup_tools path)
    mock_u2 = MagicMock(name=f"u2@{u2_port}")
    mock_u2.ping.return_value = True
    device._u2 = mock_u2
    device._tunnels_ready_channels = channels or {"u2", "stfservice"}
    device._tunnels = mock_tunnels
    return send


def _full_attach(device: DeviceClient, *,
                 send: Optional[MagicMock] = None,
                 u2_port: int = 9000) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Returns (send, u2, tunnels)."""
    if send is None:
        send = _make_send()
    _attach(device, send=send, u2_port=u2_port)
    return send, device._u2, device._tunnels


# ═══════════════════════════════════════════════════════════════════════════════
# attach_agent_sender — state reset on reconnect
# ═══════════════════════════════════════════════════════════════════════════════

class TestAttachAgentSenderReset:
    """attach_agent_sender must reset session state so on_agent_ready sees is_initial=True."""

    def test_clears_tunnels_ready_channels(self):
        d = _make_device()
        _attach(d, u2_port=9000)
        assert d._tunnels_ready_channels  # non-empty after first session

        new_send = _make_send("new")
        mock_tunnels = MagicMock()
        mock_tunnels.start_all.return_value = {"u2": 9100, "stfservice": 9101}
        with patch("runtime.core.device_client.TunnelSet", return_value=mock_tunnels):
            d.attach_agent_sender(new_send)

        assert d._tunnels_ready_channels == set()  # reset for is_initial detection

    def test_nulls_stale_u2_client(self):
        d = _make_device()
        old_send, old_u2, _ = _full_attach(d, u2_port=9000)
        assert d._u2 is old_u2

        new_send = _make_send("new")
        mock_tunnels = MagicMock()
        mock_tunnels.start_all.return_value = {"u2": 9100, "stfservice": 9101}
        with patch("runtime.core.device_client.TunnelSet", return_value=mock_tunnels):
            d.attach_agent_sender(new_send)

        assert d._u2 is None  # old port client discarded

    def test_updates_agent_send(self):
        d = _make_device()
        old_send = _make_send("old")
        _attach(d, send=old_send)
        new_send = _make_send("new")
        mock_tunnels = MagicMock()
        mock_tunnels.start_all.return_value = {"u2": 9100, "stfservice": 9101}
        with patch("runtime.core.device_client.TunnelSet", return_value=mock_tunnels):
            d.attach_agent_sender(new_send)
        assert d._agent_send is new_send

    def test_updates_tunnel_ports(self):
        d = _make_device()
        _attach(d, u2_port=9000)
        new_send = _make_send("new")
        mock_tunnels = MagicMock()
        mock_tunnels.start_all.return_value = {"u2": 9100, "stfservice": 9101}
        with patch("runtime.core.device_client.TunnelSet", return_value=mock_tunnels):
            d.attach_agent_sender(new_send)
        assert d._tunnel_ports["u2"] == 9100

    def test_on_agent_ready_is_initial_after_attach(self):
        """After attach_agent_sender resets _tunnels_ready_channels, on_agent_ready
        must start _setup_tools (is_initial=True path)."""
        d = _make_device()
        old_send = _make_send("old")
        _attach(d, send=old_send)

        new_send = _make_send("new")
        mock_tunnels = MagicMock()
        mock_tunnels.start_all.return_value = {"u2": 9100, "stfservice": 9101}
        with patch("runtime.core.device_client.TunnelSet", return_value=mock_tunnels):
            d.attach_agent_sender(new_send)

        setup_calls = []
        with patch.object(d, "_setup_tools", side_effect=lambda: setup_calls.append(1)):
            with patch("threading.Thread") as mock_thread:
                # Simulate on_agent_ready detecting is_initial=True
                d.on_agent_ready(ready_channels={"u2", "stfservice"})
                # Thread should be created for _setup_tools (is_initial path)
                assert mock_thread.called


# ═══════════════════════════════════════════════════════════════════════════════
# on_agent_disconnected — no sender (backward compatibility)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDisconnectedNoSender:

    def test_clears_u2(self):
        d = _make_device()
        _attach(d)
        d.on_agent_disconnected()
        assert d._u2 is None

    def test_clears_agent_send(self):
        d = _make_device()
        _attach(d)
        d.on_agent_disconnected()
        assert d._agent_send is None

    def test_clears_tunnels_ready_channels(self):
        d = _make_device()
        _attach(d)
        d.on_agent_disconnected()
        assert d._tunnels_ready_channels == set()

    def test_stops_tunnels(self):
        d = _make_device()
        _attach(d)
        tunnels = d._tunnels
        d.on_agent_disconnected()
        tunnels.stop_all.assert_called_once()
        assert d._tunnels is None

    def test_clears_latest_jpeg(self):
        d = _make_device()
        _attach(d)
        with d._latest_jpeg_lock:
            d._latest_jpeg = b"\xff\xd8\xff"
        d.on_agent_disconnected()
        with d._latest_jpeg_lock:
            assert d._latest_jpeg is None

    def test_clears_last_key_frame(self):
        d = _make_device()
        _attach(d)
        d._last_key_frame = {"type": "frame", "data": "abc"}
        d.on_agent_disconnected()
        assert d._last_key_frame is None

    def test_stops_stf_service(self):
        d = _make_device()
        _attach(d)
        mock_stf = MagicMock()
        d._stf_service = mock_stf
        d.on_agent_disconnected()
        mock_stf.stop_client.assert_called_once()
        assert d._stf_service is None

    def test_state_becomes_disconnected(self):
        d = _make_device()
        _attach(d)
        d.on_agent_disconnected()
        assert d.state == DeviceState.DISCONNECTED

    def test_dead_state_not_overwritten(self):
        d = _make_device()
        _attach(d)
        d._state = DeviceState.DEAD
        d.on_agent_disconnected()
        assert d.state == DeviceState.DEAD

    def test_tunnels_none_does_not_raise(self):
        """Safe when _tunnels is already None (e.g. called twice)."""
        d = _make_device()
        _attach(d)
        d._tunnels = None
        d.on_agent_disconnected()  # must not raise

    def test_idempotent_second_call(self):
        d = _make_device()
        _attach(d)
        d.on_agent_disconnected()
        d.on_agent_disconnected()  # second call must not raise
        assert d._agent_send is None


# ═══════════════════════════════════════════════════════════════════════════════
# on_agent_disconnected — matching sender (normal disconnect)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDisconnectedMatchingSender:

    def test_tears_down_when_sender_matches(self):
        d = _make_device()
        send = _attach(d)
        d.on_agent_disconnected(sender=send)
        assert d._u2 is None
        assert d._agent_send is None
        assert d.state == DeviceState.DISCONNECTED

    def test_stops_tunnels_when_sender_matches(self):
        d = _make_device()
        send = _attach(d)
        tunnels = d._tunnels
        d.on_agent_disconnected(sender=send)
        tunnels.stop_all.assert_called_once()

    def test_clears_jpeg_when_sender_matches(self):
        d = _make_device()
        send = _attach(d)
        with d._latest_jpeg_lock:
            d._latest_jpeg = b"\xff\xd8\xff"
        d.on_agent_disconnected(sender=send)
        with d._latest_jpeg_lock:
            assert d._latest_jpeg is None

    def test_channels_cleared_when_sender_matches(self):
        d = _make_device()
        send = _attach(d)
        d.on_agent_disconnected(sender=send)
        assert d._tunnels_ready_channels == set()

    def test_on_agent_ready_sees_is_initial_after_matching_disconnect(self):
        """After a proper (matching) disconnect, _tunnels_ready_channels is empty.
        The next attach_agent_sender also resets it → on_agent_ready sees is_initial=True."""
        d = _make_device()
        send = _attach(d, channels={"u2", "stfservice"})

        # Proper disconnect clears channels
        d.on_agent_disconnected(sender=send)
        assert d._tunnels_ready_channels == set()

        # New attach_agent_sender also resets channels (even if they were leftover)
        new_send = _make_send("new")
        mock_tunnels = MagicMock()
        mock_tunnels.start_all.return_value = {"u2": 9100, "stfservice": 9101}
        with patch("runtime.core.device_client.TunnelSet", return_value=mock_tunnels):
            d.attach_agent_sender(new_send)

        # is_initial check: _tunnels_ready_channels must be empty right after attach
        assert d._tunnels_ready_channels == set()


# ═══════════════════════════════════════════════════════════════════════════════
# on_agent_disconnected — stale sender (reconnect race condition)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDisconnectedStaleSender:
    """
    Timeline simulated here:
      1. old_send = attach(device)            # first session
      2. new_send = attach(device)            # reconnect — replaces old session
      3. device.on_agent_disconnected(sender=old_send)   # old finally block fires
         → must NOT tear down the new session's state
    """

    def _setup_reconnect(self, u2_old=9000, u2_new=9100):
        d = _make_device()
        old_send = _attach(d, u2_port=u2_old)
        new_send = _attach(d, u2_port=u2_new)
        return d, old_send, new_send

    # ── Core guard ────────────────────────────────────────────────────────────

    def test_skips_teardown_when_sender_replaced(self):
        d, old_send, new_send = self._setup_reconnect()
        assert d._agent_send is new_send
        new_u2 = d._u2

        d.on_agent_disconnected(sender=old_send)

        assert d._agent_send is new_send
        assert d._u2 is new_u2

    def test_state_unchanged_when_sender_replaced(self):
        d, old_send, _ = self._setup_reconnect()
        d.on_agent_disconnected(sender=old_send)
        assert d.state == DeviceState.READY

    def test_tunnels_not_stopped_when_sender_replaced(self):
        d, old_send, _ = self._setup_reconnect()
        new_tunnels = d._tunnels
        d.on_agent_disconnected(sender=old_send)
        new_tunnels.stop_all.assert_not_called()

    def test_tunnels_ref_preserved_when_sender_replaced(self):
        d, old_send, _ = self._setup_reconnect()
        new_tunnels = d._tunnels
        d.on_agent_disconnected(sender=old_send)
        assert d._tunnels is new_tunnels

    def test_tunnel_ports_preserved_when_sender_replaced(self):
        d, old_send, _ = self._setup_reconnect(u2_new=9100)
        d.on_agent_disconnected(sender=old_send)
        assert d._tunnel_ports["u2"] == 9100

    def test_tunnels_ready_channels_preserved_when_sender_replaced(self):
        d, old_send, _ = self._setup_reconnect()
        d.on_agent_disconnected(sender=old_send)
        assert "u2" in d._tunnels_ready_channels

    def test_latest_jpeg_preserved_when_sender_replaced(self):
        d, old_send, _ = self._setup_reconnect()
        frame = b"\xff\xd8\xff\x00"
        with d._latest_jpeg_lock:
            d._latest_jpeg = frame
        d.on_agent_disconnected(sender=old_send)
        with d._latest_jpeg_lock:
            assert d._latest_jpeg is frame

    def test_last_key_frame_preserved_when_sender_replaced(self):
        d, old_send, _ = self._setup_reconnect()
        kf = {"type": "frame", "data": "abc"}
        d._last_key_frame = kf
        d.on_agent_disconnected(sender=old_send)
        assert d._last_key_frame is kf

    def test_stf_service_not_stopped_when_sender_replaced(self):
        d, old_send, _ = self._setup_reconnect()
        mock_stf = MagicMock()
        d._stf_service = mock_stf
        d.on_agent_disconnected(sender=old_send)
        mock_stf.stop_client.assert_not_called()

    # ── Identity check (is not, not ==) ───────────────────────────────────────

    def test_guard_uses_identity_not_equality(self):
        """Guard must use 'is not' so that mock.__eq__ overrides can't fool it."""
        d = _make_device()
        old_send = _attach(d)
        new_send = MagicMock(name="new_send")
        new_send.__eq__ = lambda self, other: True   # would fool '!=' check
        d._agent_send = new_send

        d.on_agent_disconnected(sender=old_send)

        assert d._agent_send is new_send  # guard correctly skipped teardown

    # ── sender=None always tears down ─────────────────────────────────────────

    def test_none_sender_always_tears_down_even_after_reconnect(self):
        d, _, new_send = self._setup_reconnect()
        d.on_agent_disconnected(sender=None)
        assert d._agent_send is None
        assert d._u2 is None

    # ── Multiple sequential reconnects ────────────────────────────────────────

    def test_three_sequential_reconnects(self):
        """Each old finally fires after the next session is live — only last session survives."""
        d = _make_device()
        sends = []
        for port in (9000, 9100, 9200):
            s = _attach(d, u2_port=port)
            sends.append(s)

        final_u2 = d._u2
        final_send = sends[-1]

        # All stale finally blocks fire
        d.on_agent_disconnected(sender=sends[0])
        d.on_agent_disconnected(sender=sends[1])

        assert d._agent_send is final_send
        assert d._u2 is final_u2
        assert d.state == DeviceState.READY

    def test_last_session_disconnect_tears_down(self):
        """When the truly-last session disconnects (matching sender), teardown happens."""
        d = _make_device()
        old_send = _attach(d, u2_port=9000)
        new_send = _attach(d, u2_port=9100)

        d.on_agent_disconnected(sender=old_send)  # stale — skip
        assert d._agent_send is new_send

        d.on_agent_disconnected(sender=new_send)  # real disconnect
        assert d._agent_send is None
        assert d.state == DeviceState.DISCONNECTED


# ═══════════════════════════════════════════════════════════════════════════════
# Full reconnect sequence (end-to-end simulation)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullReconnectSequence:
    """
    Simulates the exact ws.py flow when agent reconnects:

    ws.py (new handler):
      1. attach_agent_sender(new_send)        → _tunnels_ready_channels reset, _u2 nulled
      2. state → CONNECTING
      3. old_ws.close() sent
      4. on_agent_status()                    → state → READY
      5. on_agent_ready({u2, stfservice})     → is_initial=True → _setup_tools

    ws.py (old handler finally):
      6. on_agent_disconnected(sender=old_send)  → stale, skip
    """

    def test_new_session_u2_reconnects_after_race(self):
        """After attach_agent_sender, on_agent_ready must see is_initial=True
        so _setup_tools (and u2 reconnect) is triggered."""
        d = _make_device()

        # Step 1: first session fully established
        old_send = _make_send("old")
        _attach(d, send=old_send, u2_port=9000)
        assert "u2" in d._tunnels_ready_channels  # old session ready

        # Step 2: new session attaches (reconnect race — before old finally fires)
        new_send = _make_send("new")
        mock_tunnels_new = MagicMock(name="new_tunnels")
        mock_tunnels_new.start_all.return_value = {
            "u2": 9100, "stfservice": 9101
        }
        with patch("runtime.core.device_client.TunnelSet", return_value=mock_tunnels_new):
            d.attach_agent_sender(new_send)

        # After attach, _tunnels_ready_channels must be empty
        assert d._tunnels_ready_channels == set()
        # And _u2 must be null (old port discarded)
        assert d._u2 is None

        # Step 3: on_agent_ready for new session
        setup_started = threading.Event()
        def fake_setup():
            setup_started.set()

        with patch.object(d, "_setup_tools", side_effect=fake_setup):
            with patch.object(d, "_u2_keepalive_loop"):  # don't start real loop
                d.on_agent_ready(ready_channels={"u2", "stfservice"})
                setup_started.wait(timeout=1.0)

        assert setup_started.is_set(), "_setup_tools was not called (is_initial was False)"

        # Step 4: old finally fires — must not tear down new session
        d.on_agent_disconnected(sender=old_send)
        assert d._agent_send is new_send

    def test_tunnel_ports_reflect_new_session_after_race(self):
        d = _make_device()
        old_send = _attach(d, u2_port=9000)
        assert d._tunnel_ports["u2"] == 9000

        # Reconnect
        new_send = _make_send("new")
        mock_tunnels = MagicMock()
        mock_tunnels.start_all.return_value = {"u2": 9100, "stfservice": 9101}
        with patch("runtime.core.device_client.TunnelSet", return_value=mock_tunnels):
            d.attach_agent_sender(new_send)

        # Stale disconnect
        d.on_agent_disconnected(sender=old_send)

        assert d._tunnel_ports["u2"] == 9100  # new port preserved

    def test_reconnect_does_not_affect_scrcpy_receiver(self):
        """Scrcpy receiver is managed separately; reconnect guard must not touch it."""
        d = _make_device()
        old_send = _attach(d, u2_port=9000)
        mock_scrcpy = MagicMock(name="scrcpy_receiver")
        d._scrcpy_receiver = mock_scrcpy

        # New session replaces old
        new_send = _attach(d, u2_port=9100)

        d.on_agent_disconnected(sender=old_send)

        # Scrcpy receiver should not be touched by the stale disconnect
        assert d._scrcpy_receiver is mock_scrcpy


# ═══════════════════════════════════════════════════════════════════════════════
# Thread safety
# ═══════════════════════════════════════════════════════════════════════════════

class TestThreadSafety:

    def test_concurrent_stale_and_real_disconnect_no_deadlock(self):
        """Two threads: one with stale sender, one with real sender. No deadlock."""
        d = _make_device()
        old_send = _attach(d, u2_port=9000)
        new_send = _attach(d, u2_port=9100)

        results = {}
        errors = []

        def stale():
            try:
                d.on_agent_disconnected(sender=old_send)
                results["stale"] = "ok"
            except Exception as e:
                errors.append(e)

        def real():
            try:
                time.sleep(0.01)  # slight delay so stale fires first
                d.on_agent_disconnected(sender=new_send)
                results["real"] = "ok"
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=stale)
        t2 = threading.Thread(target=real)
        t1.start(); t2.start()
        t1.join(timeout=2.0); t2.join(timeout=2.0)

        assert not errors, f"Exceptions: {errors}"
        assert not t1.is_alive(), "stale thread deadlocked"
        assert not t2.is_alive(), "real thread deadlocked"
        assert results.get("stale") == "ok"
        assert results.get("real") == "ok"
        # After real disconnect fires, state should be DISCONNECTED
        assert d.state == DeviceState.DISCONNECTED

    def test_concurrent_attach_and_disconnect_no_crash(self):
        """attach_agent_sender + on_agent_disconnected racing should not crash."""
        d = _make_device()
        old_send = _attach(d, u2_port=9000)
        errors = []

        def reconnect():
            for port in range(9100, 9105):
                try:
                    new_send = _make_send(f"send@{port}")
                    mock_t = MagicMock()
                    mock_t.start_all.return_value = {
                        "u2": port, "stfservice": port + 1
                    }
                    with patch("runtime.core.device_client.TunnelSet", return_value=mock_t):
                        d.attach_agent_sender(new_send)
                except Exception as e:
                    errors.append(e)

        def disconnect():
            for _ in range(5):
                try:
                    d.on_agent_disconnected(sender=old_send)
                except Exception as e:
                    errors.append(e)
                time.sleep(0.001)

        t1 = threading.Thread(target=reconnect)
        t2 = threading.Thread(target=disconnect)
        t1.start(); t2.start()
        t1.join(timeout=2.0); t2.join(timeout=2.0)

        assert not errors, f"Exceptions: {errors}"
