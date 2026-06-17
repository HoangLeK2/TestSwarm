from __future__ import annotations

import asyncio

import pytest

from unittest.mock import patch

from relay.extra_data.collector import (
    build_ingest_payload,
    collect_fb_comment_filter_apply,
    collect_fb_comment_target_with_tap,
    collect_xml_snapshots,
    expand_see_more_via_u2,
    _looks_like_hierarchy_xml,
    _maybe_open_fb_post_detail,
    _u2_click_comment_target,
    _u2_click_post_open_target,
)

_SAMPLE_XML = '<?xml version="1.0"?><hierarchy><node text="hi"/></hierarchy>'
_SEE_MORE_XML = """<?xml version="1.0"?>
<hierarchy>
  <node class="android.widget.Button" clickable="true" bounds="[100,200][300,250]"
        text="Xem thêm"/>
</hierarchy>"""


class _FakeExecutor:
    def __init__(self, xml: str = _SAMPLE_XML, window: tuple[int, int] = (1080, 2340)) -> None:
        self.xml = xml
        self._dump_xml = xml
        self.window = window
        self.batches: list[list[dict]] = []
        self.clicks: list[tuple[int, int]] = []
        self.selector_clicks = 0
        self.press_back_calls = 0

    async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        self.batches.append(actions)
        results: list[dict] = []
        for act in actions:
            op = act.get("op")
            if op == "dump_hierarchy":
                results.append({"op": op, "ok": True, "value": self._dump_xml})
            elif op == "swipe":
                results.append({"op": op, "ok": True})
            elif op == "click":
                self.clicks.append((int(act["x"]), int(act["y"])))
                results.append({"op": op, "ok": True})
            elif op == "click_spec":
                self.clicks.append(("u2", "click_spec", act))
                results.append({"op": op, "ok": True, "value": True})
            elif op == "wait_exists":
                results.append({"op": op, "ok": True, "value": True})
            elif op == "click_selector":
                self.selector_clicks += 1
                hit = self.selector_clicks <= 1
                results.append({"op": op, "ok": True, "value": hit})
            elif op == "press_key":
                self.press_back_calls += 1
                results.append({"op": op, "ok": True})
            else:
                return {"ok": False, "results": results, "error": "unexpected"}
        return {"ok": True, "results": results}

    async def window_size(self, serial: str) -> tuple[int, int]:
        return self.window


class _SpecMissExecutor(_FakeExecutor):
    async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        if actions and actions[0].get("op") == "click_spec":
            self.batches.append(actions)
            return {
                "ok": True,
                "results": [{"op": "click_spec", "ok": True, "value": False}],
            }
        if actions and actions[0].get("op") == "click_selector":
            self.batches.append(actions)
            self.selector_clicks += 1
            return {
                "ok": True,
                "results": [{"op": "click_selector", "ok": True, "value": True}],
            }
        return await super().run_batch(serial, actions, early_exit=early_exit)


class _SessionFakeExecutor(_FakeExecutor):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.session_scope_calls = 0

    async def with_session(self, serial: str, coro):
        self.session_scope_calls += 1
        return await coro()


class _CancelAfterFirstSwipeExecutor(_FakeExecutor):
    def __init__(self, cancel_event: asyncio.Event, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cancel_event = cancel_event
        self.swipes = 0

    async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        result = await super().run_batch(serial, actions, early_exit=early_exit)
        if any(action.get("op") == "swipe" for action in actions):
            self.swipes += 1
            self.cancel_event.set()
        return result


def test_looks_like_hierarchy_xml() -> None:
    assert _looks_like_hierarchy_xml(_SAMPLE_XML)
    assert not _looks_like_hierarchy_xml("<hierarchy />")


@pytest.mark.asyncio
async def test_collect_single_snapshot() -> None:
    exec_ = _FakeExecutor()
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "ig_posts",
        {},
    )
    assert err is None
    assert len(snapshots) == 1
    assert snapshots[0] == _SAMPLE_XML
    assert not any(
        action.get("op") == "screenshot"
        for batch in exec_.batches
        for action in batch
    )


@pytest.mark.asyncio
async def test_collect_fb_comments_default_scan_is_bounded() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    exec_ = _FakeExecutor(xml=_sheet_xml())
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {"comment_scroll_pause_s": 0},
    )
    assert err is None
    assert snapshots
    swipes = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "swipe"
    ]
    dumps = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "dump_hierarchy"
    ]
    assert len(swipes) <= 6
    assert len(dumps) <= 3


@pytest.mark.asyncio
async def test_collect_comment_snapshots_with_scroll() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    exec_ = _FakeExecutor(xml=_sheet_xml())
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {"comment_scroll_passes": 2, "min_comment_scan_passes": 1},
    )
    assert err is None
    assert len(snapshots) >= 1
    assert any(a[0].get("op") == "swipe" for a in exec_.batches if a)


class _GrowingXmlExecutor(_FakeExecutor):
    """Returns a unique hierarchy on every dump so XML never repeats — isolates
    the wall-clock cap as the stopping reason (no no-growth / no-new short-circuit)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._n = 0

    async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
            self._n += 1
            self._dump_xml = (
                f'<?xml version="1.0"?><hierarchy><node text="c{self._n}"/></hierarchy>'
            )
        return await super().run_batch(serial, actions, early_exit=early_exit)


@pytest.mark.asyncio
async def test_comment_scroll_wall_clock_cap_stops_early() -> None:
    """A tiny wall-clock budget must bound the comment phase well below the full
    scroll budget, even when XML keeps changing (no no-growth early-stop)."""
    exec_ = _GrowingXmlExecutor()
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {
            "comment_scroll_passes": 20,
            "comment_swipes_per_dump": 3,
            "comment_scroll_pause_s": 0,
            "comment_scroll_wall_s": 0.0001,
        },
    )
    assert err is None
    assert snapshots  # at least the initial snapshot
    swipes = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "swipe"
    ]
    # Wall cap breaks at the first loop check, so at most one swipe batch runs —
    # far below the 20-pass budget (and below the no-new break of ~12 swipes).
    assert len(swipes) <= 3, f"wall cap should bound swipes, got {len(swipes)}"


@pytest.mark.asyncio
async def test_collect_returns_error_when_dump_fails() -> None:
    exec_ = _FakeExecutor(xml="<hierarchy />")
    snapshots, err = await collect_xml_snapshots(exec_, "dev1", "fb_posts", {})
    assert snapshots == []
    assert err == "u2_hierarchy_unavailable"


class _SeeMoreOnceExecutor(_FakeExecutor):
    """After first coordinate tap (xml path), hierarchy no longer contains 'Xem thêm'."""

    async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        if actions and actions[0].get("op") == "click_selector":
            return {
                "ok": True,
                "results": [{"op": "click_selector", "ok": True, "value": False}],
            }
        if any(act.get("op") == "click" for act in actions):
            self._dump_xml = _SAMPLE_XML
        return await super().run_batch(serial, actions, early_exit=early_exit)


def _batches_with_dump(batches: list[list[dict]]) -> list[list[dict]]:
    return [
        b for b in batches
        if b and any(act.get("op") == "dump_hierarchy" for act in b)
    ]


@pytest.mark.asyncio
async def test_expand_fast_selector_taps() -> None:
    exec_ = _FakeExecutor()
    taps, cached = await expand_see_more_via_u2(
        exec_,
        "dev1",
        {"expand_see_more": True, "expand_see_more_max_passes": 1},
    )
    assert taps == 1
    assert cached is None
    assert exec_.selector_clicks >= 1
    assert not any(b and b[0].get("op") == "dump_hierarchy" for b in exec_.batches)


@pytest.mark.asyncio
async def test_expand_fast_noop_without_selector_match() -> None:
    exec_ = _FakeExecutor()

    async def _never_click(serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        exec_.batches.append(actions)
        if actions and actions[0].get("op") == "click_selector":
            return {"ok": True, "results": [{"op": "click_selector", "ok": True, "value": False}]}
        return await _FakeExecutor.run_batch(exec_, serial, actions, early_exit)

    exec_.run_batch = _never_click  # type: ignore[method-assign]
    taps, cached = await expand_see_more_via_u2(
        exec_,
        "dev1",
        {"expand_see_more": True, "expand_see_more_xml_probe": False},
    )
    assert taps == 0
    assert cached is None
    assert not any(b and b[0].get("op") == "dump_hierarchy" for b in exec_.batches)


@pytest.mark.asyncio
async def test_expand_xml_probe_first_for_fb_posts() -> None:
    exec_ = _SeeMoreOnceExecutor(xml=_SEE_MORE_XML)
    taps, cached = await expand_see_more_via_u2(
        exec_,
        "dev1",
        {"expand_see_more": True, "expand_see_more_xml_probe_first": True},
    )
    assert taps == 1
    assert cached == _SAMPLE_XML
    assert exec_.clicks == [(200, 225)]
    assert not any(b and b[0].get("op") == "click_selector" for b in exec_.batches)
    assert len(_batches_with_dump(exec_.batches)) == 2


@pytest.mark.asyncio
async def test_collect_fb_posts_uses_xml_probe_first() -> None:
    exec_ = _SeeMoreOnceExecutor(xml=_SEE_MORE_XML)
    await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_posts",
        {"expand_see_more": True},
    )
    assert exec_.clicks == [(200, 225)]
    assert not any(b and b[0].get("op") == "click_selector" for b in exec_.batches)


@pytest.mark.asyncio
async def test_expand_xml_probe_when_selector_misses() -> None:
    exec_ = _SeeMoreOnceExecutor(xml=_SEE_MORE_XML)

    async def _never_selector(serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        if actions and actions[0].get("op") == "click_selector":
            return {"ok": True, "results": [{"op": "click_selector", "ok": True, "value": False}]}
        return await _SeeMoreOnceExecutor.run_batch(exec_, serial, actions, early_exit)

    exec_.run_batch = _never_selector  # type: ignore[method-assign]
    taps, cached = await expand_see_more_via_u2(
        exec_,
        "dev1",
        {"expand_see_more": True, "expand_see_more_xml_probe": True},
    )
    assert taps == 1
    assert cached == _SAMPLE_XML
    assert exec_.clicks == [(200, 225)]
    assert len(_batches_with_dump(exec_.batches)) == 2


@pytest.mark.asyncio
async def test_expand_xml_probe_first_no_see_more_reuses_probe_xml() -> None:
    exec_ = _FakeExecutor(xml=_SAMPLE_XML)
    taps, cached = await expand_see_more_via_u2(
        exec_,
        "dev1",
        {
            "expand_see_more": True,
            "expand_see_more_xml_probe_first": True,
            "expand_see_more_fast": False,
        },
    )
    assert taps == 0
    assert cached == _SAMPLE_XML
    assert len(_batches_with_dump(exec_.batches)) == 1


@pytest.mark.asyncio
async def test_expand_xml_probe_first_default_skips_selector_on_no_see_more() -> None:
    exec_ = _FakeExecutor(xml=_SAMPLE_XML)

    async def _selector_misses(serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        return await _FakeExecutor.run_batch(exec_, serial, actions, early_exit)

    exec_.run_batch = _selector_misses  # type: ignore[method-assign]
    taps, cached = await expand_see_more_via_u2(
        exec_,
        "dev1",
        {"expand_see_more": True, "expand_see_more_xml_probe_first": True},
    )

    assert taps == 0
    assert cached == _SAMPLE_XML
    assert not any(
        action.get("op") == "click_selector"
        for batch in exec_.batches
        for action in batch
    )
    assert len(_batches_with_dump(exec_.batches)) == 1


@pytest.mark.asyncio
async def test_collect_fb_posts_no_see_more_single_dump() -> None:
    exec_ = _FakeExecutor(xml=_SAMPLE_XML)
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_posts",
        {"expand_see_more": True},
    )
    assert err is None
    assert snapshots == [_SAMPLE_XML]
    assert len(_batches_with_dump(exec_.batches)) == 1


@pytest.mark.asyncio
async def test_collect_fb_comments_honors_explicit_deep_scroll_context() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    exec_ = _FakeExecutor(xml=_sheet_xml())
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {
            "comment_scroll_passes": 48,
            "comment_swipes_per_dump": 3,
            "comment_no_growth_break": 3,
            "min_comment_scan_passes": 2,
            "comment_scroll_pause_s": 0,
            "comment_recover_chrome": False,
        },
    )

    assert err is None
    assert snapshots
    swipes = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "swipe"
    ]
    dumps = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "dump_hierarchy"
    ]
    swipes_between_dumps: list[int] = []
    current = 0
    for batch in exec_.batches:
        for action in batch:
            if action.get("op") == "swipe":
                current += 1
            elif action.get("op") == "dump_hierarchy":
                if current:
                    swipes_between_dumps.append(current)
                    current = 0
    assert swipes_between_dumps == [3, 2, 2]
    assert len(swipes) == 7
    assert len(dumps) == 4


@pytest.mark.asyncio
async def test_collect_fb_comments_stops_when_cancel_event_is_set() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    cancel_event = asyncio.Event()
    exec_ = _CancelAfterFirstSwipeExecutor(cancel_event, xml=_sheet_xml())

    with pytest.raises(asyncio.CancelledError):
        await collect_xml_snapshots(
            exec_,
            "dev1",
            "fb_comments",
            {
                "_cancel_event": cancel_event,
                "comment_scroll_passes": 48,
                "comment_swipes_per_dump": 3,
                "comment_no_growth_break": 3,
                "min_comment_scan_passes": 2,
                "comment_scroll_pause_s": 0,
                "comment_recover_chrome": False,
            },
        )

    assert exec_.swipes == 1


@pytest.mark.asyncio
async def test_expand_xml_fallback_when_selector_misses() -> None:
    exec_ = _SeeMoreOnceExecutor(xml=_SEE_MORE_XML)

    async def _mixed_batch(serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        if actions and actions[0].get("op") == "click_selector":
            return {"ok": True, "results": [{"op": "click_selector", "ok": True, "value": False}]}
        return await _SeeMoreOnceExecutor.run_batch(exec_, serial, actions, early_exit)

    exec_.run_batch = _mixed_batch  # type: ignore[method-assign]
    taps, cached = await expand_see_more_via_u2(
        exec_,
        "dev1",
        {
            "expand_see_more": True,
            "expand_see_more_xml_probe": False,
            "expand_see_more_xml_fallback": True,
            "expand_see_more_max_passes": 1,
        },
    )
    assert taps == 1
    assert exec_.clicks == [(200, 225)]
    assert any(b and b[0].get("op") == "dump_hierarchy" for b in exec_.batches)


@pytest.mark.asyncio
async def test_expand_xml_legacy_when_fast_disabled() -> None:
    exec_ = _SeeMoreOnceExecutor(xml=_SEE_MORE_XML)
    taps, cached = await expand_see_more_via_u2(
        exec_,
        "dev1",
        {
            "expand_see_more": True,
            "expand_see_more_fast": False,
            "expand_see_more_max_passes": 1,
        },
    )
    assert taps == 1
    assert cached is None
    assert exec_.batches[0][0]["op"] == "dump_hierarchy"
    assert exec_.batches[1][0]["op"] == "click"


@pytest.mark.asyncio
async def test_expand_see_more_skipped_when_disabled() -> None:
    exec_ = _FakeExecutor(xml=_SEE_MORE_XML)
    taps, cached = await expand_see_more_via_u2(exec_, "dev1", {"expand_see_more": False})
    assert taps == 0
    assert cached is None
    assert exec_.selector_clicks == 0


@pytest.mark.asyncio
async def test_collect_fb_posts_probe_then_final_dump() -> None:
    exec_ = _SeeMoreOnceExecutor(xml=_SEE_MORE_XML)
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_posts",
        {"expand_see_more": True, "expand_see_more_max_passes": 1},
    )
    assert err is None
    assert len(snapshots) == 1
    assert len(_batches_with_dump(exec_.batches)) == 2
    assert exec_.clicks == [(200, 225)]
    assert not any(b and b[0].get("op") == "click_selector" for b in exec_.batches)


@pytest.mark.asyncio
async def test_collect_fb_comment_target_prefers_click_spec() -> None:
    exec_ = _SessionFakeExecutor()
    diagnostic = {
        "reason_code": "ok",
        "target": {
            "bounds": [100, 200, 300, 250],
            "u2_click": {
                "xpath": '//*[@bounds="[100,200][300,250]"]',
                "spec": {"xpath": '//*[@bounds="[100,200][300,250]"]'},
                "selector": {"text": "Bình luận", "clickable": True},
            },
        },
        "alternates": [],
    }
    with patch(
        "relay.extra_data.ingest._parse_items",
        return_value=([], diagnostic),
    ):
        _snapshots, err, tapped, diag = await collect_fb_comment_target_with_tap(
            exec_,
            "dev1",
            {"post_tap_wait_s": 0.0, "comment_target_verify": False},
        )
    assert err is None
    assert tapped is True
    assert exec_.clicks[0][1] == "click_spec"
    assert diag["verify_attempts"][0]["click_route"] == "click_spec"
    click_spec = next(
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "click_spec"
    )
    assert click_spec["timeout"] == 0.35


@pytest.mark.asyncio
async def test_comment_target_default_u2_click_timeout_is_fast() -> None:
    exec_ = _FakeExecutor()
    cand = {
        "bounds": [100, 200, 300, 250],
        "u2_click": {"spec": {"text": "Bình luận"}},
    }

    ok, route = await _u2_click_comment_target(exec_, "dev1", cand, {})

    assert ok is True
    assert route == "click_spec"
    assert exec_.batches[0][0]["timeout"] == 0.35


@pytest.mark.asyncio
async def test_comment_target_does_not_use_global_selector_fallback_by_default() -> None:
    exec_ = _SpecMissExecutor()
    cand = {
        "bounds": [100, 200, 300, 250],
        "u2_click": {
            "spec": {"xpath": '//*[@bounds="[100,200][300,250]"]'},
            "selector": {"text": "Bình luận", "clickable": True},
        },
    }

    ok, route = await _u2_click_comment_target(exec_, "dev1", cand, {})

    assert ok is True
    assert route == "click_coord"
    assert exec_.selector_clicks == 0
    assert exec_.clicks == [(244, 225)]


@pytest.mark.asyncio
async def test_post_open_defaults_to_coordinate_tap() -> None:
    exec_ = _FakeExecutor()
    target = {
        "bounds": [100, 200, 500, 260],
        "tap_kind": "timestamp",
        "u2_click": {"spec": {"text": "5 giờ"}},
    }

    ok, route = await _u2_click_post_open_target(exec_, "dev1", target, {})

    assert ok is True
    assert route == "click_coord"
    assert exec_.clicks == [(240, 230)]


@pytest.mark.asyncio
async def test_post_open_u2_click_is_explicit_fallback_only() -> None:
    exec_ = _SpecMissExecutor()
    target = {
        "bounds": [100, 200, 500, 260],
        "tap_kind": "timestamp",
        "u2_click": {"spec": {"text": "5 giờ"}},
    }

    async def _coord_miss(_executor, serial: str, x: int, y: int) -> bool:
        exec_.clicks.append((x, y))
        return False

    with patch("relay.extra_data.collector._u2_click", side_effect=_coord_miss):
        ok, route = await _u2_click_post_open_target(
            exec_,
            "dev1",
            target,
            {"post_open_u2_click": True},
        )

    assert ok is False
    assert route == "tap_failed"
    assert exec_.clicks == [(240, 230)]
    assert exec_.batches[0][0]["op"] == "click_spec"
    assert exec_.batches[0][0]["timeout"] == 0.25


@pytest.mark.asyncio
async def test_collect_fb_comment_target_with_tap_same_session() -> None:
    exec_ = _SessionFakeExecutor()
    diagnostic = {
        "reason_code": "ok",
        "target": {"bounds": [100, 200, 300, 250]},
        "alternates": [],
    }
    with patch(
        "relay.extra_data.ingest._parse_items",
        return_value=([], diagnostic),
    ), patch(
        "relay.extra_data.collector._wait_comment_sheet_opened",
        return_value=(True, "wait_exists"),
    ):
        snapshots, err, tapped, diagnostic = await collect_fb_comment_target_with_tap(
            exec_,
            "dev1",
            {"post_tap_wait_s": 0.0},
        )
    assert err is None
    assert tapped is True
    assert snapshots == [_SAMPLE_XML]
    assert exec_.clicks == [(244, 225)]
    assert exec_.session_scope_calls == 1
    assert diagnostic.get("reason_code") == "ok"
    assert diagnostic.get("verified") is True
    assert diagnostic.get("chosen_index") == 0
    assert exec_.press_back_calls == 0


@pytest.mark.asyncio
async def test_collect_fb_comment_target_retries_when_sheet_did_not_open() -> None:
    exec_ = _SessionFakeExecutor()
    diagnostic = {
        "reason_code": "ok",
        "target": {"bounds": [100, 200, 300, 250], "post_key": "primary"},
        "alternates": [{"bounds": [400, 500, 600, 560], "post_key": "alt-1"}],
        "candidate_count": 2,
    }
    verify_sequence = iter([False, True])  # first tap fails, retry succeeds

    def _fake_verify(_xml):
        return next(verify_sequence)

    with patch(
        "relay.extra_data.ingest._parse_items",
        return_value=([], diagnostic),
    ), patch(
        "relay.extra_data.collector._wait_comment_sheet_opened",
        side_effect=[(False, "wait_miss"), (True, "wait_exists")],
    ), patch(
        "relay.extra_data.collector._diag_sheet_opened",
        side_effect=_fake_verify,
    ), patch(
        "relay.extra_data.parsers.facebook.comment_pipeline.should_press_back_after_failed_tap",
        return_value=True,
    ):
        snapshots, err, tapped, diag = await collect_fb_comment_target_with_tap(
            exec_,
            "dev1",
            {
                "post_tap_wait_s": 0.0,
                "comment_target_verify_back_settle_s": 0.0,
                "comment_target_verify_max_retries": 1,
            },
        )

    assert err is None
    assert tapped is True
    assert snapshots == [_SAMPLE_XML]
    assert exec_.clicks == [(244, 225), (544, 530)]
    assert exec_.press_back_calls == 1
    assert diag["verified"] is True
    assert diag["chosen_index"] == 1
    assert diag["target"]["post_key"] == "alt-1"
    assert len(diag["verify_attempts"]) == 2
    assert diag["verify_attempts"][0]["verified"] is False
    assert diag["verify_attempts"][0].get("back_pressed") is True


@pytest.mark.asyncio
async def test_collect_fb_comment_target_skips_back_on_group_feed() -> None:
    exec_ = _SessionFakeExecutor()
    feed_xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" text="Bạn viết gì đi…" bounds="[40,200][900,280]" />
</hierarchy>"""
    exec_._dump_xml = feed_xml
    diagnostic = {
        "reason_code": "ok",
        "target": {"bounds": [100, 200, 300, 250], "post_key": "primary"},
        "alternates": [{"bounds": [400, 500, 600, 560], "post_key": "alt-1"}],
    }

    with patch(
        "relay.extra_data.ingest._parse_items",
        return_value=([], diagnostic),
    ), patch(
        "relay.extra_data.collector._wait_comment_sheet_opened",
        return_value=(False, "wait_miss"),
    ), patch(
        "relay.extra_data.collector._diag_sheet_opened",
        side_effect=[False, True],
    ):
        _snapshots, err, tapped, diag = await collect_fb_comment_target_with_tap(
            exec_,
            "dev1",
            {
                "post_tap_wait_s": 0.0,
                "comment_target_verify_back_settle_s": 0.0,
                "comment_target_verify_max_retries": 1,
            },
        )

    assert err is None
    assert tapped is True
    assert exec_.press_back_calls == 0
    assert diag["verify_attempts"][0].get("back_pressed") is False
    assert diag["chosen_index"] == 1


@pytest.mark.asyncio
async def test_collect_fb_comment_target_skips_verify_when_disabled() -> None:
    exec_ = _SessionFakeExecutor()
    diagnostic = {
        "reason_code": "ok",
        "target": {"bounds": [100, 200, 300, 250], "post_key": "primary"},
        "alternates": [{"bounds": [400, 500, 600, 560], "post_key": "alt-1"}],
    }
    with patch(
        "relay.extra_data.ingest._parse_items",
        return_value=([], diagnostic),
    ), patch(
        "relay.extra_data.collector._diag_sheet_opened",
    ) as mock_verify:
        snapshots, err, tapped, diag = await collect_fb_comment_target_with_tap(
            exec_,
            "dev1",
            {"post_tap_wait_s": 0.0, "comment_target_verify": False},
        )

    assert err is None
    assert tapped is True
    assert snapshots == [_SAMPLE_XML]
    assert exec_.clicks == [(244, 225)]
    assert exec_.press_back_calls == 0
    assert diag["target"]["post_key"] == "primary"
    assert diag["chosen_index"] == 0
    assert mock_verify.call_count == 0


@pytest.mark.asyncio
async def test_collect_fb_comment_filter_apply_single_session() -> None:
    exec_ = _SessionFakeExecutor()
    phases = iter(
        [
            {"phase": "open_sheet", "reason_code": "ok", "tap": {"bounds": [10, 20, 30, 40]}},
            {"phase": "select_option", "reason_code": "ok", "tap": {"bounds": [40, 1040, 680, 1120]}},
            {"phase": "done", "reason_code": "already_on_filter", "tap": None},
        ]
    )

    def _fake_parse(strategy: str, xml: str, context: dict):
        return [], next(phases)

    with patch("relay.extra_data.ingest._parse_items", side_effect=_fake_parse):
        report, err = await collect_fb_comment_filter_apply(
            exec_,
            "dev1",
            {"comment_filter": "all_comments"},
        )
    assert err is None
    assert report["switched"] is True
    assert report["reason_code"] == "already_on_filter"
    assert len(report["steps"]) == 3
    assert exec_.clicks == [(20, 30), (360, 1080)]
    assert exec_.session_scope_calls == 1


@pytest.mark.asyncio
async def test_open_post_verify_failed_on_group_feed_no_back() -> None:
    """Failed post-detail verify on group feed must not press BACK (exits group)."""
    exec_ = _SessionFakeExecutor()
    feed_xml = """<?xml version="1.0"?>
<hierarchy>
  <node text="Nhóm công khai" bounds="[0,0][1080,100]"/>
  <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,200][1080,2200]">
    <node bounds="[0,400][1080,1100]">
      <node text="Author" bounds="[132,420][420,464]"/>
      <node text="5 ngày" bounds="[132,468][280,504]" clickable="true"/>
      <node content-desc="Post body" bounds="[36,520][1044,700]" clickable="true"/>
    </node>
  </node>
</hierarchy>"""
    exec_._dump_xml = feed_xml
    target = {
        "bounds": [132, 468, 280, 504],
        "tap_kind": "timestamp",
        "tap_label": "5 ngày",
    }
    ctx: dict = {"open_post_before_extract": True, "post_open_verify": True}
    with patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline.resolve_post_open_targets_from_xml",
        return_value=(target, []),
    ), patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline.hierarchy_is_fb_post_detail_from_xml",
        return_value=False,
    ), patch(
        "relay.extra_data.parsers.facebook.comment_pipeline.should_press_back_after_failed_tap",
        return_value=False,
    ):
        detail_xml, diag = await _maybe_open_fb_post_detail(
            exec_, "dev1", ctx, feed_xml
        )
    assert detail_xml is None
    assert diag.get("reason_code") == "post_open_verify_failed"
    assert exec_.press_back_calls == 0
    assert diag.get("attempts") and diag["attempts"][0].get("back_pressed") is False


@pytest.mark.asyncio
async def test_open_post_success_returns_opened_post_metadata() -> None:
    exec_ = _SessionFakeExecutor()
    feed_xml = """<?xml version="1.0"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,200][1080,2200]">
    <node bounds="[0,400][1080,1100]">
      <node text="Author" bounds="[132,420][420,464]"/>
      <node text="5 ngày" bounds="[132,468][280,504]" clickable="true"/>
      <node content-desc="Post body" bounds="[36,520][1044,700]" clickable="true"/>
    </node>
  </node>
</hierarchy>"""
    exec_._dump_xml = feed_xml
    target = {
        "bounds": [132, 468, 280, 504],
        "tap_kind": "timestamp",
        "tap_label": "5 ngày",
        "post": {
            "_pid": "pid-2",
            "post_key": "post-2",
            "stable_post_id": "stable-2",
            "fb_post_id": "fb-2",
            "author": "Alice",
            "timestamp": "5 ngày",
            "text": "opened post body",
        },
    }
    ctx: dict = {"open_post_before_extract": True, "post_open_verify": True}
    with patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline.resolve_post_open_targets_from_xml",
        return_value=(target, []),
    ), patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline.hierarchy_is_fb_post_detail_from_xml",
        side_effect=[False, True],
    ):
        detail_xml, diag = await _maybe_open_fb_post_detail(
            exec_, "dev1", ctx, feed_xml
        )

    assert detail_xml == feed_xml
    assert diag["reason_code"] == "ok"
    assert diag["opened_post"] == {
        "pid": "pid-2",
        "post_key": "post-2",
        "stable_post_id": "stable-2",
        "fb_post_id": "fb-2",
        "author": "Alice",
        "timestamp": "5 ngày",
        "text_prefix": "opened post body",
    }


@pytest.mark.asyncio
async def test_open_post_uses_comment_sheet_for_extract_without_marking_detail_ok() -> None:
    exec_ = _SessionFakeExecutor()
    feed_xml = """<?xml version="1.0"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,200][1080,2200]">
    <node bounds="[0,400][1080,1100]">
      <node text="Author" bounds="[132,420][420,464]"/>
      <node text="5 ngày" bounds="[132,468][280,504]" clickable="true"/>
      <node content-desc="Post body" bounds="[36,520][1044,700]" clickable="true"/>
    </node>
  </node>
</hierarchy>"""
    comment_sheet_xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" class="android.widget.Button"
        clickable="true" content-desc="Quay lại" bounds="[0,80][120,160]" />
  <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,400][1080,2350]">
    <node bounds="[0,420][1080,900]">
      <node text="Phù hợp nhất" bounds="[40,450][400,500]" />
      <node text="Commenter" bounds="[40,520][300,560]" />
      <node text="Comment body" bounds="[40,560][1000,620]" />
    </node>
  </node>
</hierarchy>"""
    exec_._dump_xml = comment_sheet_xml
    target = {
        "bounds": [132, 468, 280, 504],
        "tap_kind": "timestamp",
        "tap_label": "5 ngày",
    }
    ctx: dict = {"open_post_before_extract": True, "post_open_verify": True}
    with patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline.resolve_post_open_targets_from_xml",
        return_value=(target, []),
    ), patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline.hierarchy_is_fb_post_detail_from_xml",
        return_value=False,
    ):
        detail_xml, diag = await _maybe_open_fb_post_detail(
            exec_, "dev1", ctx, feed_xml
        )

    assert detail_xml == comment_sheet_xml
    assert diag["reason_code"] == "comment_sheet"
    assert diag["attempts"][0]["comment_sheet_opened"] is True
    assert ctx.get("open_post_detail") is True
    assert exec_.press_back_calls == 0


@pytest.mark.asyncio
async def test_collect_post_open_comment_sheet_skips_post_expand() -> None:
    exec_ = _SessionFakeExecutor()
    feed_xml = """<?xml version="1.0"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,200][1080,2200]">
    <node text="feed"/>
  </node>
</hierarchy>"""
    comment_sheet_xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" class="android.widget.Button"
        clickable="true" content-desc="Quay lại" bounds="[0,80][120,160]" />
  <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,400][1080,2350]">
    <node text="Phù hợp nhất" bounds="[40,450][400,500]" />
    <node text="Commenter" bounds="[40,520][300,560]" />
    <node text="Comment body" bounds="[40,560][1000,620]" />
  </node>
</hierarchy>"""
    exec_._dump_xml = feed_xml
    ctx: dict = {"open_post_before_extract": True, "expand_see_more": True}

    async def _opened_comment_sheet(*args, **kwargs):
        return comment_sheet_xml, {"reason_code": "comment_sheet"}

    async def _unexpected_expand(*args, **kwargs):
        raise AssertionError("post expand should be skipped on comment sheet")

    with patch(
        "relay.extra_data.collector._maybe_open_fb_post_detail",
        new=_opened_comment_sheet,
    ), patch(
        "relay.extra_data.collector.expand_see_more_via_u2",
        new=_unexpected_expand,
    ):
        snapshots, err = await collect_xml_snapshots(exec_, "dev1", "fb_posts", ctx)

    assert err is None
    assert snapshots == [comment_sheet_xml]
    assert ctx["expand_see_more_skipped"] == "comment_sheet"


@pytest.mark.asyncio
async def test_open_post_already_on_detail_avoids_extra_post_parse() -> None:
    exec_ = _SessionFakeExecutor()
    detail_xml = '<hierarchy><node text="detail"/></hierarchy>'
    ctx: dict = {"open_post_before_extract": True}

    with patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline.hierarchy_is_fb_post_detail_from_xml",
        return_value=True,
    ), patch(
        "relay.extra_data.parsers.facebook.parse_fb_posts_from_xml_with_diagnostic",
        return_value=([], {"reason_code": "empty"}),
    ) as parser_mock:
        opened_xml, diag = await _maybe_open_fb_post_detail(
            exec_, "dev1", ctx, detail_xml
        )

    assert opened_xml == detail_xml
    assert diag["reason_code"] == "already_on_post_detail"
    assert "opened_post" not in diag
    parser_mock.assert_not_called()


@pytest.mark.asyncio
async def test_comment_scroll_suppresses_back_on_group_collection() -> None:
    """IME recovery used to press BACK each dump and pop out of the FB group."""
    keyboard_sheet_xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" class="android.widget.Button"
        content-desc="Quay lại" bounds="[0,80][120,160]" />
  <node package="com.facebook.katana" text="Phù hợp nhất" bounds="[40,450][400,500]" />
  <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,400][1080,2200]" />
  <node package="com.facebook.katana" class="android.widget.EditText"
        focused="true" text="Viết bình luận…" bounds="[40,2280][1040,2340]" />
</hierarchy>"""
    exec_ = _FakeExecutor(xml=keyboard_sheet_xml)
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {
            "collection": "fb_group_posts",
            "comment_scroll_passes": 0,
            "comment_recover_chrome": True,
        },
    )
    assert err is None
    assert snapshots
    assert exec_.press_back_calls == 0


def test_build_ingest_payload_includes_snapshots() -> None:
    payload = build_ingest_payload(
        serial="dev1",
        strategy="fb_comments",
        context={"collection": "c1"},
        snapshots=[_SAMPLE_XML, _SAMPLE_XML + " "],
        request_id="extra-abc",
    )
    assert payload["serial"] == "dev1"
    assert payload["strategy"] == "fb_comments"
    assert payload["xml"] == _SAMPLE_XML
    assert payload["snapshot_count"] == 2
    assert "xml_snapshots" in payload
