"""Keep oversized blobs out of Temporal payloads.

A step result that carries raw bytes rides the whole durable path: activity
result -> workflow step_results -> every continue_as_new payload -> finalize.
Temporal warns at 256KB and refuses at 2MB, so one careless field kills the
workflow rather than degrading it. That already happened once: take_screenshot
inlined base64 (a measured 499KB JPEG is ~665KB encoded), so three of those
steps in one scenario was over the hard limit.

Fixing the one producer is not enough — the next one to inline bytes would hit
the same wall. This guard runs in the activity interceptor, so every activity
present and future is covered in one place, and it names the offending field in
the log instead of failing somewhere far away.
"""
from __future__ import annotations

import dataclasses
from typing import Any, NamedTuple

# Generous next to the 256KB warning threshold: real step fields (messages,
# selectors, extracted text) are kilobytes, so anything past this is a blob.
DEFAULT_MAX_VALUE_BYTES = 64 * 1024

# Per-field trimming says nothing about the total. Forty fields of 60KB each is
# 2.4MB with nothing over the field limit — Temporal refuses that payload and the
# log shows no dropped field at all. Warn here so the growth is visible before
# the hard limit, not after.
SOFT_TOTAL_WARN_BYTES = 1024 * 1024

_MAX_DEPTH = 12

# Fields that feed back into scenario execution rather than describing it.
# Runtime variables ride home in DeviceActionBatchResult.context["vars"] and
# become the next step's inputs, so silently swapping one for a placeholder
# would let the scenario keep running on corrupted data — strictly worse than
# hitting Temporal's limit with a clear error. A variable that large is an
# authoring problem and should fail loudly.
_PROTECTED_FIELDS = frozenset({"context"})


# Only fields at least this large can matter in a top-5 of a ~1MB payload.
# Bounds the bookkeeping list so the guard stays cheap on normal results.
_TRACK_FIELD_MIN_BYTES = 1024


class PayloadScan(NamedTuple):
    dropped: list[str]
    total_bytes: int
    largest: list[tuple[str, int]]


def _placeholder(size: int, limit: int) -> str:
    return f"<dropped: {size} bytes exceeds the {limit} byte payload limit>"


def scan_payload(
    value: Any,
    *,
    limit: int = DEFAULT_MAX_VALUE_BYTES,
) -> PayloadScan:
    """Trim over-limit fields in place and measure what is left.

    Containers are mutated rather than rebuilt so the caller keeps the original
    dataclass types Temporal expects to serialize.
    """
    state = _ScanState(limit)
    _walk(value, limit, "", state, set(), 0)
    state.largest.sort(key=lambda item: item[1], reverse=True)
    return PayloadScan(state.dropped, state.total_bytes, state.largest[:5])


def strip_oversized_values(
    value: Any,
    *,
    limit: int = DEFAULT_MAX_VALUE_BYTES,
) -> list[str]:
    """Back-compat view of scan_payload: just the dropped paths."""
    return scan_payload(value, limit=limit).dropped


class _ScanState:
    __slots__ = ("limit", "dropped", "total_bytes", "largest")

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.dropped: list[str] = []
        self.total_bytes = 0
        self.largest: list[tuple[str, int]] = []

    def record(self, path: str, size: int) -> None:
        self.total_bytes += size
        if size >= _TRACK_FIELD_MIN_BYTES:
            self.largest.append((path, size))


def _measure(item: Any) -> int | None:
    if isinstance(item, str):
        return len(item.encode("utf-8", "ignore"))
    if isinstance(item, (bytes, bytearray)):
        return len(item)
    return None


def _handle_leaf(item: Any, path: str, state: _ScanState) -> int | None:
    """Return the size if the item is over-limit and must be replaced."""
    size = _measure(item)
    if size is None:
        return None
    if size > state.limit:
        # The placeholder is what actually ships, so that is what counts.
        state.record(path, len(_placeholder(size, state.limit)))
        state.dropped.append(path)
        return size
    state.record(path, size)
    return None


def _walk(
    node: Any,
    limit: int,
    path: str,
    state: _ScanState,
    seen: set[int],
    depth: int,
) -> None:
    if depth > _MAX_DEPTH or node is None:
        return
    # Cycles are not expected in activity results, but a guard must not be the
    # thing that hangs the worker.
    if id(node) in seen:
        return

    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        seen.add(id(node))
        for f in dataclasses.fields(node):
            if f.name in _PROTECTED_FIELDS:
                continue
            child = getattr(node, f.name, None)
            child_path = f"{path}.{f.name}" if path else f.name
            size = _handle_leaf(child, child_path, state)
            if size is not None:
                setattr(node, f.name, _placeholder(size, limit))
            else:
                _walk(child, limit, child_path, state, seen, depth + 1)
        return

    if isinstance(node, dict):
        seen.add(id(node))
        for key, child in list(node.items()):
            if key in _PROTECTED_FIELDS:
                continue
            child_path = f"{path}.{key}" if path else str(key)
            size = _handle_leaf(child, child_path, state)
            if size is not None:
                node[key] = _placeholder(size, limit)
            else:
                _walk(child, limit, child_path, state, seen, depth + 1)
        return

    if isinstance(node, list):
        seen.add(id(node))
        for i, child in enumerate(node):
            child_path = f"{path}[{i}]"
            size = _handle_leaf(child, child_path, state)
            if size is not None:
                node[i] = _placeholder(size, limit)
            else:
                _walk(child, limit, child_path, state, seen, depth + 1)
        return
