"""An extract that fails must say why.

``_handle_extra_data`` replies ok=false plus an error string. When that string
came back empty the farm substituted the literal "extra_data_failed", and the
operator saw "Thu thập dữ liệu bài viết thất bại" with no cause attached —
the real reason (usually a u2 session that would not connect) was gone.

Bare ``asyncio.TimeoutError`` is the common empty-message offender: it is what
``asyncio.wait_for`` raises, and the u2 session pool sits on two of them.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from relay.agent import RelayAgent
from relay.u2_session_pool import CONNECT_TIMEOUT_SECONDS, U2SessionPool


class _FakeIngest:
    async def process_payload(self, payload: dict) -> dict:  # pragma: no cover
        return {"ok": True}


class _FakeExecutor:
    async def with_session(self, serial: str, coro):  # pragma: no cover
        return await coro()


def _agent() -> RelayAgent:
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key=None,
        relay_id="test-relay",
        relay_mode="grpc",
        extra_ingest=_FakeIngest(),
    )
    agent._u2_executor = _FakeExecutor()
    return agent


async def _reply_for_collect_raising(exc: BaseException) -> dict:
    agent = _agent()
    queue: asyncio.Queue = asyncio.Queue()

    async def _raise(executor, serial, strategy, context):
        raise exc

    with patch("relay.extra_data.collector.collect_xml_snapshots", new=_raise):
        await agent._handle_extra_data(
            {
                "id": "extra-1",
                "serial": "dev1",
                "strategy": "fb_posts",
                "context": {},
            },
            queue,
        )

    return json.loads(await asyncio.wait_for(queue.get(), timeout=2.0))


@pytest.mark.asyncio
async def test_message_less_exception_still_names_its_type() -> None:
    msg = await _reply_for_collect_raising(asyncio.TimeoutError())

    assert msg["ok"] is False
    assert msg["error"] == "TimeoutError"


@pytest.mark.asyncio
async def test_exception_with_a_message_keeps_it() -> None:
    msg = await _reply_for_collect_raising(
        TimeoutError("u2 connect timed out after 20.0s serial=dev1")
    )

    assert msg["ok"] is False
    assert msg["error"] == "u2 connect timed out after 20.0s serial=dev1"


@pytest.mark.asyncio
async def test_pool_connect_timeout_carries_a_message() -> None:
    pool = U2SessionPool(
        asyncio.get_running_loop(),
        connect_fn=lambda host: None,
    )

    async def _timeout(*args, **kwargs):
        raise asyncio.TimeoutError()

    with patch("asyncio.wait_for", new=_timeout):
        with pytest.raises(TimeoutError) as caught:
            await pool._connect("dev1")

    # Still a TimeoutError, so upstream except-clauses keep working; it just
    # carries the story now instead of an empty string.
    assert str(caught.value) == (
        f"u2 connect timed out after {CONNECT_TIMEOUT_SECONDS}s serial=dev1"
    )


@pytest.mark.asyncio
async def test_connect_timeout_message_avoids_dead_session_markers() -> None:
    """The retry gate matches on error text — do not trip it by accident."""
    from relay.u2_executor import _DEAD_SESSION_MARKERS

    message = f"u2 connect timed out after {CONNECT_TIMEOUT_SECONDS}s serial=dev1".lower()

    assert not [marker for marker in _DEAD_SESSION_MARKERS if marker in message]
