"""A post must only get its comment button tapped once per run.

Without this guard a feed loop re-resolves "the comment button nearest
mid-screen" on every iteration and taps the same card again and again.
"""

from __future__ import annotations

from typing import Any

import pytest

from tasks.scenario.steps.extraction import (
    _CONSUMED_POST_ANCHORS_CTX_KEY,
    _MAX_CONSUMED_POST_ANCHORS,
    _remember_consumed_comment_parent,
)


def _ctx_with_parent(pid: str, *, author: str = "A", ts: str = "1h", text: str = "body") -> dict[str, Any]:
    return {
        "_active_comment_parent_anchor": {
            "pid": pid,
            "author": author,
            "timestamp": ts,
            "text_prefix": text,
        },
        "_active_comment_parent_hash": f"hash-{pid}",
        "_comment_parent_pid": pid,
    }


def test_same_post_recorded_once() -> None:
    ctx = _ctx_with_parent("p1")
    _remember_consumed_comment_parent(ctx)
    _remember_consumed_comment_parent(ctx)
    _remember_consumed_comment_parent(ctx)
    assert len(ctx[_CONSUMED_POST_ANCHORS_CTX_KEY]) == 1


def test_distinct_posts_accumulate() -> None:
    ctx = _ctx_with_parent("p1")
    _remember_consumed_comment_parent(ctx)
    ctx.update(_ctx_with_parent("p2", author="B", ts="2h", text="other"))
    _remember_consumed_comment_parent(ctx)
    pids = [a.get("pid") for a in ctx[_CONSUMED_POST_ANCHORS_CTX_KEY]]
    assert pids == ["p1", "p2"]


def test_anchor_list_is_bounded() -> None:
    ctx: dict[str, Any] = {}
    for i in range(_MAX_CONSUMED_POST_ANCHORS + 25):
        ctx.update(_ctx_with_parent(f"p{i}", author=f"A{i}", ts=f"{i}h", text=f"t{i}"))
        _remember_consumed_comment_parent(ctx)
    bucket = ctx[_CONSUMED_POST_ANCHORS_CTX_KEY]
    assert len(bucket) == _MAX_CONSUMED_POST_ANCHORS
    # Oldest entries are dropped, newest kept.
    assert bucket[-1]["pid"] == f"p{_MAX_CONSUMED_POST_ANCHORS + 24}"


def test_empty_parent_is_not_recorded() -> None:
    ctx: dict[str, Any] = {}
    _remember_consumed_comment_parent(ctx)
    assert not ctx.get(_CONSUMED_POST_ANCHORS_CTX_KEY)


def test_consumed_anchors_are_sent_to_the_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exclusion list must actually reach agent-boot, not just sit in ctx."""
    from tasks.scenario.steps import extraction as ex

    captured: dict[str, Any] = {}

    class _Device:
        def request_extra_data_xml(self, **kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": False, "error": "stop-here"}

    # The relay guard is transport-level and irrelevant to what we assert here.
    monkeypatch.setattr(ex, "_relay_extra_data_available", lambda _device: True)

    ctx = _ctx_with_parent("p1")
    _remember_consumed_comment_parent(ctx)

    result: dict[str, Any] = {}
    ex.request_edge_comment_target(
        device=_Device(),
        serial="serial-1",
        ctx=ctx,
        scenario={"_execution_id": "exec-1"},
        step={},
        result=result,
        cancel_event=None,
        agent_tap=False,
    )

    context = captured.get("context") or {}
    excluded = context.get("comment_exclude_anchors")
    assert excluded, "consumed posts must be forwarded as an exclusion list"
    assert excluded[0]["pid"] == "p1"
