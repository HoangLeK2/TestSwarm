from __future__ import annotations

import pytest

from runtime.transports.adb_relay_server import AdbRelayManager


def test_next_a11y_seq_monotonic_per_device():
    rm = AdbRelayManager()
    assert rm.next_a11y_seq("dev-1") == 1
    assert rm.next_a11y_seq("dev-1") == 2
    assert rm.next_a11y_seq("dev-2") == 1
    assert rm.next_a11y_seq("dev-1") == 3


@pytest.mark.asyncio
async def test_a11y_mutate_no_relay_returns_error():
    rm = AdbRelayManager()
    result = await rm.a11y_mutate(
        serial="unknown-serial",
        action="tap",
        payload={"x": 1, "y": 2},
        session_id="s1",
        timeout=1.0,
    )
    assert result["ok"] is False
    assert result["accepted"] is False
    assert "no relay" in result["error"]
