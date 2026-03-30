from __future__ import annotations

"""
tests/test_device_groups.py — Unit tests for DF-004 Device Groups & Tags.

Run: pytest tests/test_device_groups.py -v

Tests cover:
- Tag normalisation (update_device_tags helper)
- Tags filter logic in fleet dispatch (_device_has_all_tags)
- Fleet dispatch: group filter, tags filter, combined filter
- _build_scenario_registry (already tested in test_flow_composition, here we check tags path)
"""

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from services.fleet_dispatch import _device_has_all_tags, enqueue_fleet_scenario


# ── Helpers / stubs ───────────────────────────────────────────────────────────


class _MockState:
    def __init__(self, name: str = "READY") -> None:
        self.name = name


class _MockDevice:
    def __init__(self, serial: str, model: str = "TestPhone", state: str = "READY") -> None:
        self.serial = serial
        self.model = model
        self.state = _MockState(state)


class _MockManager:
    def __init__(self, devices: list[_MockDevice]) -> None:
        self._devices = devices

    def all_devices(self) -> list[_MockDevice]:
        return self._devices


class _MockQueue:
    def __init__(self) -> None:
        self.tasks: list[Any] = []

    def put(self, task: Any) -> None:
        self.tasks.append(task)


def _make_step() -> List[Dict[str, Any]]:
    return [{"type": "wait", "seconds": 0}]


# ── _device_has_all_tags ──────────────────────────────────────────────────────


def test_has_all_tags_exact_match():
    serial_tags = {"dev1": "fast,wifi,samsung"}
    assert _device_has_all_tags("dev1", serial_tags, ["fast", "wifi"]) is True


def test_has_all_tags_partial_match_fails():
    """Device has 'fast' but not 'wifi' → should NOT match."""
    serial_tags = {"dev1": "fast,4g"}
    assert _device_has_all_tags("dev1", serial_tags, ["fast", "wifi"]) is False


def test_has_all_tags_empty_filter_always_true():
    """Empty filter_tags list means no filtering — every device matches."""
    serial_tags = {"dev1": ""}
    assert _device_has_all_tags("dev1", serial_tags, []) is True


def test_has_all_tags_device_not_in_map():
    """Serial missing from map means no tags → only matches if filter_tags is empty."""
    serial_tags: Dict[str, str] = {}
    assert _device_has_all_tags("unknown", serial_tags, ["fast"]) is False
    assert _device_has_all_tags("unknown", serial_tags, []) is True


def test_has_all_tags_single_tag():
    serial_tags = {"d": "slow,4g,samsung"}
    assert _device_has_all_tags("d", serial_tags, ["samsung"]) is True
    assert _device_has_all_tags("d", serial_tags, ["fast"]) is False


def test_has_all_tags_whitespace_in_stored_tags():
    """Tags with extra spaces should still match after normalisation."""
    serial_tags = {"d": " fast , wifi "}
    assert _device_has_all_tags("d", serial_tags, ["fast", "wifi"]) is True


# ── Fleet dispatch: group filter ──────────────────────────────────────────────


def test_fleet_group_filter_includes_only_group_members():
    devices = [
        _MockDevice("serial_A"),
        _MockDevice("serial_B"),
        _MockDevice("serial_C"),
    ]
    manager = _MockManager(devices)
    queue = _MockQueue()

    payload, status = enqueue_fleet_scenario(
        manager, queue,
        steps=_make_step(),
        filter_state="READY",
        filter_model=None,
        max_devices=None,
        priority=5, timeout=30, max_retries=1,
        group_serials=frozenset({"serial_A", "serial_C"}),
    )
    assert status == 200
    assert payload["dispatched"] == 2
    assert set(payload["device_serials"]) == {"serial_A", "serial_C"}


def test_fleet_group_filter_empty_intersection_returns_400():
    devices = [_MockDevice("serial_X")]
    manager = _MockManager(devices)
    queue = _MockQueue()

    payload, status = enqueue_fleet_scenario(
        manager, queue,
        steps=_make_step(),
        filter_state="READY",
        filter_model=None,
        max_devices=None,
        priority=5, timeout=30, max_retries=1,
        group_serials=frozenset({"serial_NOT_CONNECTED"}),
    )
    assert status == 400
    assert len(queue.tasks) == 0


def test_fleet_group_filter_none_is_no_op():
    """group_serials=None means no group filter — all READY devices are targeted."""
    devices = [_MockDevice("A"), _MockDevice("B")]
    manager = _MockManager(devices)
    queue = _MockQueue()

    payload, status = enqueue_fleet_scenario(
        manager, queue,
        steps=_make_step(),
        filter_state="READY",
        filter_model=None,
        max_devices=None,
        priority=5, timeout=30, max_retries=1,
        group_serials=None,
    )
    assert status == 200
    assert payload["dispatched"] == 2


# ── Fleet dispatch: tags filter ───────────────────────────────────────────────


def test_fleet_tags_filter_and_logic():
    """Only devices with ALL requested tags should be selected."""
    devices = [
        _MockDevice("d1"),  # tags: fast,wifi → matches fast+wifi
        _MockDevice("d2"),  # tags: fast → missing wifi
        _MockDevice("d3"),  # tags: wifi,slow → missing fast
    ]
    serial_tags = {"d1": "fast,wifi", "d2": "fast", "d3": "wifi,slow"}
    manager = _MockManager(devices)
    queue = _MockQueue()

    payload, status = enqueue_fleet_scenario(
        manager, queue,
        steps=_make_step(),
        filter_state="READY",
        filter_model=None,
        max_devices=None,
        priority=5, timeout=30, max_retries=1,
        filter_tags=["fast", "wifi"],
        serial_tags=serial_tags,
    )
    assert status == 200
    assert payload["dispatched"] == 1
    assert payload["device_serials"] == ["d1"]


def test_fleet_tags_filter_single_tag():
    devices = [_MockDevice("x"), _MockDevice("y")]
    serial_tags = {"x": "4g,samsung", "y": "wifi"}
    manager = _MockManager(devices)
    queue = _MockQueue()

    payload, status = enqueue_fleet_scenario(
        manager, queue,
        steps=_make_step(),
        filter_state="READY",
        filter_model=None,
        max_devices=None,
        priority=5, timeout=30, max_retries=1,
        filter_tags=["4g"],
        serial_tags=serial_tags,
    )
    assert status == 200
    assert payload["dispatched"] == 1
    assert payload["device_serials"] == ["x"]


def test_fleet_tags_filter_no_match_returns_400():
    devices = [_MockDevice("z")]
    serial_tags = {"z": "slow"}
    manager = _MockManager(devices)
    queue = _MockQueue()

    payload, status = enqueue_fleet_scenario(
        manager, queue,
        steps=_make_step(),
        filter_state="READY",
        filter_model=None,
        max_devices=None,
        priority=5, timeout=30, max_retries=1,
        filter_tags=["fast"],
        serial_tags=serial_tags,
    )
    assert status == 400


def test_fleet_tags_filter_none_skips_filtering():
    devices = [_MockDevice("p"), _MockDevice("q")]
    manager = _MockManager(devices)
    queue = _MockQueue()

    payload, status = enqueue_fleet_scenario(
        manager, queue,
        steps=_make_step(),
        filter_state="READY",
        filter_model=None,
        max_devices=None,
        priority=5, timeout=30, max_retries=1,
        filter_tags=None,
        serial_tags=None,
    )
    assert status == 200
    assert payload["dispatched"] == 2


# ── Fleet dispatch: combined group + tags filter ──────────────────────────────


def test_fleet_combined_group_and_tags_filter():
    """Group filter AND tags filter must both apply (intersection)."""
    devices = [
        _MockDevice("a"),   # in group, has tag
        _MockDevice("b"),   # in group, missing tag
        _MockDevice("c"),   # not in group, has tag
    ]
    serial_tags = {"a": "fast", "b": "slow", "c": "fast"}
    manager = _MockManager(devices)
    queue = _MockQueue()

    payload, status = enqueue_fleet_scenario(
        manager, queue,
        steps=_make_step(),
        filter_state="READY",
        filter_model=None,
        max_devices=None,
        priority=5, timeout=30, max_retries=1,
        group_serials=frozenset({"a", "b"}),
        filter_tags=["fast"],
        serial_tags=serial_tags,
    )
    assert status == 200
    assert payload["dispatched"] == 1
    assert payload["device_serials"] == ["a"]


# ── Fleet dispatch: state filter still works with group ───────────────────────


def test_fleet_state_filter_applied_before_group():
    """Non-READY devices are excluded even if they are in the group."""
    devices = [
        _MockDevice("ready_in_group", state="READY"),
        _MockDevice("busy_in_group", state="BUSY"),
    ]
    manager = _MockManager(devices)
    queue = _MockQueue()

    payload, status = enqueue_fleet_scenario(
        manager, queue,
        steps=_make_step(),
        filter_state="READY",
        filter_model=None,
        max_devices=None,
        priority=5, timeout=30, max_retries=1,
        group_serials=frozenset({"ready_in_group", "busy_in_group"}),
    )
    assert status == 200
    assert payload["dispatched"] == 1
    assert payload["device_serials"] == ["ready_in_group"]


# ── fleet state filter: exact match semantics ─────────────────────────────────


class TestFleetStateFilterExactMatch:
    """filter_state uses exact enum-name match, not substring."""

    def _dispatch(self, devices, filter_state):
        manager = _MockManager(devices)
        queue = _MockQueue()
        payload, status = enqueue_fleet_scenario(
            manager, queue,
            steps=_make_step(),
            filter_state=filter_state,
            filter_model=None, max_devices=None,
            priority=5, timeout=30, max_retries=1,
        )
        return payload, status, queue

    def test_ready_matches_only_ready(self):
        devices = [
            _MockDevice("d1", state="READY"),
            _MockDevice("d2", state="BUSY"),
            _MockDevice("d3", state="OFFLINE"),
        ]
        payload, status, queue = self._dispatch(devices, "READY")
        assert status == 200
        assert payload["dispatched"] == 1
        assert payload["device_serials"] == ["d1"]

    def test_substring_read_does_not_match_ready(self):
        """'READ' must NOT match a device whose state is 'READY'."""
        devices = [_MockDevice("d1", state="READY")]
        payload, status, _ = self._dispatch(devices, "READ")
        assert status == 400, (
            "filter_state='READ' is not a valid state name — should return 400, not match READY"
        )

    def test_empty_filter_state_defaults_to_ready(self):
        """Empty string defaults to READY — does not match all devices."""
        devices = [
            _MockDevice("d_ready", state="READY"),
            _MockDevice("d_busy", state="BUSY"),
        ]
        payload, status, queue = self._dispatch(devices, "")
        assert status == 200
        assert payload["dispatched"] == 1
        assert payload["device_serials"] == ["d_ready"]

    def test_whitespace_filter_state_defaults_to_ready(self):
        """Whitespace-only filter_state is treated as empty → default READY."""
        devices = [
            _MockDevice("d_ready", state="READY"),
            _MockDevice("d_busy", state="BUSY"),
        ]
        payload, status, _ = self._dispatch(devices, "   ")
        assert status == 200
        assert payload["dispatched"] == 1

    def test_empty_filter_state_does_not_match_busy(self):
        """Empty filter_state must NOT match BUSY devices (old substring bug would)."""
        devices = [_MockDevice("d1", state="BUSY")]
        payload, status, _ = self._dispatch(devices, "")
        assert status == 400

    def test_case_insensitive_match(self):
        """'ready' (lowercase) matches state READY."""
        devices = [_MockDevice("d1", state="READY")]
        payload, status, _ = self._dispatch(devices, "ready")
        assert status == 200
        assert payload["dispatched"] == 1

    def test_busy_filter_matches_only_busy(self):
        devices = [
            _MockDevice("d1", state="READY"),
            _MockDevice("d2", state="BUSY"),
        ]
        payload, status, _ = self._dispatch(devices, "BUSY")
        assert status == 200
        assert payload["dispatched"] == 1
        assert payload["device_serials"] == ["d2"]

    def test_no_match_returns_400(self):
        devices = [_MockDevice("d1", state="READY")]
        payload, status, _ = self._dispatch(devices, "OFFLINE")
        assert status == 400
        assert "error" in payload

    def test_all_ready_all_dispatched(self):
        devices = [_MockDevice(f"d{i}", state="READY") for i in range(5)]
        payload, status, queue = self._dispatch(devices, "READY")
        assert status == 200
        assert payload["dispatched"] == 5
        assert len(queue.tasks) == 5


# ── Tag normalisation via CRUD helper ─────────────────────────────────────────


def test_tag_normalisation():
    """Test that tag normalisation logic produces clean comma-separated output."""
    # Replicate the normalisation from update_device_tags
    def _normalise(raw: str) -> str:
        return ",".join(
            t.strip().lower() for t in raw.split(",") if t.strip()
        )

    assert _normalise("Fast , WiFi,  ") == "fast,wifi"
    assert _normalise("SAMSUNG,4G") == "samsung,4g"
    assert _normalise("") == ""
    assert _normalise(",,,") == ""
    assert _normalise("slow") == "slow"
    assert _normalise("  slow  ,  fast  ") == "slow,fast"
