"""Two routers must not register the same (method, path).

`POST /api/devices/{device_id}/claim` was declared twice: device_reserve.py
(lease a session, body required) and devices.py (register an allocated pool
phone, no body). FastAPI routes to the first match and documents the last, so
the register dialog's body-less call got the lease route's 422 while OpenAPI
showed no body at all. Every route test mounted one router, so nothing failed.
"""
from __future__ import annotations

from collections import defaultdict

from api.crud.router import api_router


def test_no_duplicate_method_path_pairs():
    seen: dict[tuple[str, str], list[str]] = defaultdict(list)
    for route in api_router.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        for method in methods:
            seen[(method, path)].append(
                f"{route.endpoint.__module__}.{route.endpoint.__name__}"
            )

    duplicates = {key: names for key, names in seen.items() if len(names) > 1}
    assert not duplicates, f"shadowed routes (only the first one ever runs): {duplicates}"
