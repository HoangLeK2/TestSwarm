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
    # RecyclerView in _sheet_xml: [0,200][720,1550] — swipe in body column, not avatar strip.
    assert fx >= int(720 * 0.72)
    assert fx <= 720
    assert 200 < fy < 1550
    assert 200 <= ty < fy
    assert fy - ty >= 220


def test_resolve_comment_scroll_swipe_missing_scrollable_returns_none() -> None:
    xml = '<?xml version="1.0"?><hierarchy><node text="hi"/></hierarchy>'
    assert resolve_comment_scroll_swipe_from_xml(xml) is None


class _CommentScrollExecutor:
    def __init__(self, xml: str) -> None:
        self.xml = xml
        self.batches: list[list[dict]] = []
        self._dump_index = 0

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
    # RecyclerView swipe first; if hierarchy yields no new comment rows, one screen-fallback swipe.
    assert 1 <= len(swipes) <= 2
    fx, fy, tx, ty = swipes[0]["fx"], swipes[0]["fy"], swipes[0]["tx"], swipes[0]["ty"]
    assert int(720 * 0.72) <= fx <= 720
    assert 200 < fy < 1550
    assert ty < fy
    assert fy - ty >= 220
    assert swipes[0]["duration"] >= 0.32
    assert len(snapshots) >= 1


class _RotatingCommentScrollExecutor(_CommentScrollExecutor):
    """Each dump returns a different hierarchy so collector keeps frames."""

    def __init__(self, frames: list[str]) -> None:
        super().__init__(frames[0])
        self._frames = frames
        self._dump_index = 1  # frame 0 is the initial snapshot before scroll

    async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        for act in actions:
            if act.get("op") == "dump_hierarchy":
                idx = min(self._dump_index, len(self._frames) - 1)
                self.xml = self._frames[idx]
                self._dump_index += 1
                break
        return await super().run_batch(serial, actions, early_exit=early_exit)


@pytest.mark.asyncio
async def test_collect_comment_snapshots_keeps_distinct_xml_frames() -> None:
    base = _sheet_xml()
    frames = [
        base.replace('bounds="[0,300][720,900]"', 'bounds="[0,300][720,900]" marker="frame-a"'),
        base.replace('bounds="[0,300][720,900]"', 'bounds="[0,300][720,900]" marker="frame-b"'),
        base.replace('bounds="[0,300][720,900]"', 'bounds="[0,300][720,900]" marker="frame-c"'),
        base.replace('bounds="[0,300][720,900]"', 'bounds="[0,300][720,900]" marker="frame-d"'),
    ]
    exec_ = _RotatingCommentScrollExecutor(frames)
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {
            "comment_scroll_passes": 6,
            "comment_swipes_per_dump": 1,
            "min_comment_scan_passes": 0,
            "comment_no_growth_break": 3,
            "comment_scroll_pause_s": 0,
            "comment_recover_chrome": False,
        },
    )
    assert err is None
    assert len(snapshots) >= 3
    joined = "\n".join(snapshots)
    assert "frame-b" in joined and "frame-d" in joined


def _comment_sheet_with_body(body: str, marker: str) -> str:
    return f"""<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]" marker="{marker}">
  <node package="com.facebook.katana" class="android.widget.Button"
        clickable="true" content-desc="Quay lại" bounds="[0,80][120,160]" />
  <node package="com.facebook.katana" text="Phù hợp nhất" bounds="[40,450][400,500]" />
  <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,400][1080,2200]">
    <node bounds="[0,720][1080,900]">
      <node text="Nguyễn A" bounds="[180,740][300,780]" />
      <node text="{body}" bounds="[180,780][1000,840]" />
    </node>
  </node>
  <node package="com.facebook.katana" text="Viết bình luận…" bounds="[40,2280][1040,2340]" />
</hierarchy>"""


@pytest.mark.asyncio
async def test_collect_comment_snapshots_breaks_when_xml_changes_without_new_comments() -> None:
    frames = [
        _comment_sheet_with_body("Đúng bài này", "frame-a"),
        _comment_sheet_with_body("Đúng bài này", "frame-b"),
        _comment_sheet_with_body("Đúng bài này", "frame-c"),
        _comment_sheet_with_body("Đúng bài này", "frame-d"),
    ]
    exec_ = _RotatingCommentScrollExecutor(frames)
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {
            "comment_scroll_passes": 12,
            "comment_swipes_per_dump": 1,
            "comment_no_new_threshold": 2,
            "min_comment_scan_passes": 0,
            "comment_scroll_pause_s": 0,
            "comment_recover_chrome": False,
        },
    )

    assert err is None
    assert len(snapshots) == 2
    swipes = [a for batch in exec_.batches for a in batch if a.get("op") == "swipe"]
    assert len(swipes) == 2


@pytest.mark.asyncio
async def test_collect_comment_snapshots_reuses_swipe_coords_within_batch(monkeypatch) -> None:
    xml = _sheet_xml()
    exec_ = _CommentScrollExecutor(xml)
    calls = 0

    def fake_resolve(xml_arg: str, *, distance_ratio: float = 0.22):
        nonlocal calls
        calls += 1
        assert xml_arg == xml
        return 540, 1100, 540, 760

    monkeypatch.setattr(
        "relay.extra_data.parsers.facebook.comment_pipeline.resolve_comment_scroll_swipe_from_xml",
        fake_resolve,
    )

    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {
            "comment_scroll_passes": 3,
            "comment_swipes_per_dump": 3,
            "min_comment_scan_passes": 0,
            "comment_scroll_pause_s": 0,
        },
    )

    assert err is None
    assert snapshots
    assert calls == 1
