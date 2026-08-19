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
from typing import Any

# Generous next to the 256KB warning threshold: real step fields (messages,
# selectors, extracted text) are kilobytes, so anything past this is a blob.
DEFAULT_MAX_VALUE_BYTES = 64 * 1024

_MAX_DEPTH = 12

# Fields that feed back into scenario execution rather than describing it.
# Runtime variables ride home in DeviceActionBatchResult.context["vars"] and
# become the next step's inputs, so silently swapping one for a placeholder
# would let the scenario keep running on corrupted data — strictly worse than
# hitting Temporal's limit with a clear error. A variable that large is an
# authoring problem and should fail loudly.
_PROTECTED_FIELDS = frozenset({"context"})


def _placeholder(size: int, limit: int) -> str:
    return f"<dropped: {size} bytes exceeds the {limit} byte payload limit>"


def strip_oversized_values(
    value: Any,
    *,
    limit: int = DEFAULT_MAX_VALUE_BYTES,
) -> list[str]:
    """Replace over-limit strings/bytes in place. Returns the paths dropped.

    Containers are mutated rather than rebuilt so the caller keeps the original
    dataclass types Temporal expects to serialize.
    """
    dropped: list[str] = []
    _walk(value, limit, "", dropped, set(), 0)
    return dropped


def _too_big(item: Any, limit: int) -> int | None:
    if isinstance(item, str):
        size = len(item.encode("utf-8", "ignore"))
    elif isinstance(item, (bytes, bytearray)):
        size = len(item)
    else:
        return None
    return size if size > limit else None


def _walk(
    node: Any,
    limit: int,
    path: str,
    dropped: list[str],
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
            size = _too_big(child, limit)
            if size is not None:
                setattr(node, f.name, _placeholder(size, limit))
                dropped.append(f"{path}.{f.name}" if path else f.name)
            else:
                _walk(child, limit, f"{path}.{f.name}" if path else f.name, dropped, seen, depth + 1)
        return

    if isinstance(node, dict):
        seen.add(id(node))
        for key, child in list(node.items()):
            if key in _PROTECTED_FIELDS:
                continue
            child_path = f"{path}.{key}" if path else str(key)
            size = _too_big(child, limit)
            if size is not None:
                node[key] = _placeholder(size, limit)
                dropped.append(child_path)
            else:
                _walk(child, limit, child_path, dropped, seen, depth + 1)
        return

    if isinstance(node, list):
        seen.add(id(node))
        for i, child in enumerate(node):
            child_path = f"{path}[{i}]"
            size = _too_big(child, limit)
            if size is not None:
                node[i] = _placeholder(size, limit)
                dropped.append(child_path)
            else:
                _walk(child, limit, child_path, dropped, seen, depth + 1)
        return
