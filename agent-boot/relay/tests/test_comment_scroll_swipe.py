from __future__ import annotations

import pytest

from relay.extra_data.collector import collect_xml_snapshots
from relay.extra_data.parsers.facebook.comment_pipeline import resolve_comment_scroll_swipe_from_xml
from relay.tests.test_comment_filter import _sheet_xml


def test_resolve_comment_scroll_swipe_uses_scrollable_bounds() -> None:
    xml = _sheet_xml()
    swipe = resolve_comment_scroll_swipe_from_xml(xml, distance_ratio=0.22)
    assert swipe is not None
    fx, fy, tx, ty = swipe
    # RecyclerView in _sheet_xml: [0,200][720,1550]
    assert 0 <= fx <= 720
    assert 200 < fy < 1550
    assert 200 <= ty < fy


def test_resolve_comment_scroll_swipe_missing_scrollable_returns_none() -> None:
    xml = '<?xml version="1.0"?><hierarchy><node text="hi"/></hierarchy>'
    assert resolve_comment_scroll_swipe_from_xml(xml) is None


class _CommentScrollExecutor:
    def __init__(self, xml: str) -> None:
        self.xml = xml
        self.batches: list[list[dict]] = []

    async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        self.batches.append(actions)
        results = []
        for act in actions:
            if act.get("op") == "dump_hierarchy":
                results.append({"op": act["op"], "ok": True, "value": self.xml})
            elif act.get("op") == "swipe":
                results.append({"op": act["op"], "ok": True})
            else:
                return {"ok": False, "results": results}
        return {"ok": True, "results": results}

    async def window_size(self, serial: str) -> tuple[int, int]:
        return 720, 1600


@pytest.mark.asyncio
async def test_collect_comment_snapshots_swipe_inside_scrollable_node() -> None:
    xml = _sheet_xml()
    exec_ = _CommentScrollExecutor(xml)
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {"comment_scroll_passes": 1, "min_comment_scan_passes": 0},
    )
    assert err is None
    swipes = [a for batch in exec_.batches for a in batch if a.get("op") == "swipe"]
    assert len(swipes) == 1
    fx, fy, tx, ty = swipes[0]["fx"], swipes[0]["fy"], swipes[0]["tx"], swipes[0]["ty"]
    assert 0 <= fx <= 720
    assert 200 < fy < 1550
    assert ty < fy
    assert len(snapshots) >= 1
