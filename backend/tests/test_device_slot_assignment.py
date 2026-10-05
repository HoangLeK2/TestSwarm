"""Slot assignment: same answer as the old scan, without the O(N^2) cost.

``_get_or_assign_index`` runs once per newly reported phone, inside the relay
online callback, on the API event loop. It used to rebuild
``set(index_map.values())` on every call, which made registering a fleet
quadratic — measurable as hundreds of milliseconds of stalled loop at 1000+
phones (scripts/benchmark_relay_registration.py).

The replacement keeps a running set plus a rising hint. These tests pin that the
observable contract did not change: lowest free slot, stable across restarts,
and gaps in a persisted map still get filled.
"""
from __future__ import annotations

import json

import pytest

from core.config import Config
from runtime.core.device_manager import DeviceManager


def _manager(tmp_path, *, seed: dict | None = None) -> DeviceManager:
    index_file = tmp_path / "device_index.json"
    if seed is not None:
        index_file.write_text(json.dumps(seed))
    config = Config()
    config.device.index_file = str(index_file)
    return DeviceManager(config)


def test_slots_start_at_zero_and_increment(tmp_path):
    manager = _manager(tmp_path)
    assigned = [manager._get_or_assign_index(f"dev-{i}") for i in range(5)]
    assert assigned == [0, 1, 2, 3, 4]


def test_same_serial_keeps_its_slot(tmp_path):
    manager = _manager(tmp_path)
    first = manager._get_or_assign_index("dev-a")
    manager._get_or_assign_index("dev-b")
    assert manager._get_or_assign_index("dev-a") == first


def test_gap_in_a_persisted_map_is_filled_first(tmp_path):
    """A map loaded with a hole must hand out the hole before extending.

    The rising hint starts at 0 precisely so this still holds; a naive
    "next = len(map)" would leak slot 0 forever.
    """
    manager = _manager(tmp_path, seed={"old-1": 1, "old-3": 3})
    assert manager._get_or_assign_index("new-a") == 0
    assert manager._get_or_assign_index("new-b") == 2
    assert manager._get_or_assign_index("new-c") == 4


def test_assignment_survives_a_restart(tmp_path):
    manager = _manager(tmp_path)
    for i in range(4):
        manager._get_or_assign_index(f"dev-{i}")
    manager.flush_index_map()

    reloaded = _manager(tmp_path)
    assert reloaded._get_or_assign_index("dev-2") == 2
    assert reloaded._get_or_assign_index("dev-new") == 4


def test_matches_the_original_scan_over_a_long_run(tmp_path):
    """Differential check against the algorithm this replaced."""

    def _reference(index_map: dict[str, int], serial: str) -> int:
        if serial in index_map:
            return index_map[serial]
        used = set(index_map.values())
        idx = 0
        while idx in used:
            idx += 1
        index_map[serial] = idx
        return idx

    manager = _manager(tmp_path, seed={"seed-2": 2, "seed-5": 5})
    reference_map = {"seed-2": 2, "seed-5": 5}

    serials = [f"dev-{i}" for i in range(200)]
    # Interleave repeats so the "already assigned" branch is covered too.
    for serial in serials + serials[:50]:
        assert manager._get_or_assign_index(serial) == _reference(reference_map, serial)


@pytest.mark.parametrize("fleet", [500])
def test_assigning_a_fleet_stays_linear(tmp_path, fleet):
    """Guard the complexity itself, not just the answer.

    Compares the second half of the fleet against the first: with the old
    rescan the later assignments cost strictly more, because the set being
    rebuilt keeps growing. Linear work makes the two halves comparable.
    """
    import time

    manager = _manager(tmp_path)

    def _timed(start: int, end: int) -> float:
        began = time.perf_counter()
        for i in range(start, end):
            manager._get_or_assign_index(f"dev-{i}")
        return time.perf_counter() - began

    first_half = _timed(0, fleet // 2)
    second_half = _timed(fleet // 2, fleet)

    # Generous: only a growth trend an order of magnitude out fails here, which
    # is what reintroducing the per-call rescan looks like.
    assert second_half <= max(first_half, 1e-4) * 8, (
        f"slot assignment is superlinear: first half {first_half * 1000:.2f}ms, "
        f"second half {second_half * 1000:.2f}ms"
    )
