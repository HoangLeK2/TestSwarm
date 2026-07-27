from __future__ import annotations

import asyncio
import hashlib

import pytest

from unittest.mock import patch

from relay.extra_data.collector import (
    build_ingest_payload,
    collect_fb_comment_filter_apply,
    collect_fb_comment_target_with_tap,
    collect_xml_snapshots,
    expand_see_more_via_u2,
    release_collect_lock,
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
        self._ui_generations: dict[str, int] = {}
        self._ui_mutations_in_flight: dict[str, int] = {}

    def ui_generation(self, serial: str) -> int:
        return self._ui_generations.get(serial, 0)

    def ui_mutation_in_flight(self, serial: str) -> int:
        return self._ui_mutations_in_flight.get(serial, 0)

    def begin_ui_mutation(self, serial: str) -> None:
        self._ui_generations[serial] = self.ui_generation(serial) + 1
        self._ui_mutations_in_flight[serial] = (
            self.ui_mutation_in_flight(serial) + 1
        )

    def end_ui_mutation(self, serial: str) -> None:
        self._ui_generations[serial] = self.ui_generation(serial) + 1
        remaining = self.ui_mutation_in_flight(serial) - 1
        if remaining > 0:
            self._ui_mutations_in_flight[serial] = remaining
        else:
            self._ui_mutations_in_flight.pop(serial, None)

    async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        read_only_ops = {
            "dump_hierarchy",
            "exists",
            "get_text",
            "screenshot",
            "sleep",
            "wait_exists",
            "wait_gone",
        }
        mutates_ui = any(
            action.get("op") not in read_only_ops
            for action in actions
        )
        if mutates_ui:
            self.begin_ui_mutation(serial)
        self.batches.append(actions)
        results: list[dict] = []
        for act in actions:
            op = act.get("op")
            if op == "dump_hierarchy":
                results.append({"op": op, "ok": True, "value": self._dump_xml})
            elif op == "swipe":
                results.append({"op": op, "ok": True})
            elif op == "u2_swipe_batch":
                results.append({"op": op, "ok": True, "value": int(act.get("count") or 0)})
            elif op == "click":
                self.clicks.append((int(act["x"]), int(act["y"])))
                results.append({"op": op, "ok": True})
            elif op == "click_spec":
                self.clicks.append(("u2", "click_spec", act))
                results.append({"op": op, "ok": True, "value": True})
            elif op == "wait_exists":
                results.append({"op": op, "ok": True, "value": True})
            elif op == "wait_gone":
                results.append({"op": op, "ok": True, "value": True})
            elif op == "click_selector":
                self.selector_clicks += 1
                hit = self.selector_clicks <= 1
                results.append({"op": op, "ok": True, "value": hit})
            elif op == "press_key":
                self.press_back_calls += 1
                results.append({"op": op, "ok": True})
            elif op == "sleep":
                results.append({"op": op, "ok": True})
            else:
                if mutates_ui:
                    self.end_ui_mutation(serial)
                return {"ok": False, "results": results, "error": "unexpected"}
        if mutates_ui:
            self.end_ui_mutation(serial)
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
    assert len(dumps) <= 5


@pytest.mark.asyncio
async def test_collect_fb_comments_auto_back_closes_comment_sheet(monkeypatch) -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    import relay.extra_data.parsers.facebook as facebook

    def fake_parse(xml, parent_post_id=None, max_items=400):
        return [{"comment_key": "c1", "text": "real comment"}], {"reason_code": "ok"}

    monkeypatch.setattr(facebook, "parse_fb_comments_from_xml_with_diagnostic", fake_parse)

    exec_ = _FakeExecutor(xml=_sheet_xml())
    context = {
        "comment_scroll_passes": 1,
        "min_comment_scan_passes": 1,
        "comment_scroll_pause_s": 0,
        "open_post_press_back_after_extract": True,
    }
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert snapshots
    assert exec_.press_back_calls == 1
    assert context["comment_sheet_closed_after_extract"] is True


@pytest.mark.asyncio
async def test_collect_fb_comments_auto_back_marks_empty_rows_but_still_closes_sheet(monkeypatch) -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    import relay.extra_data.parsers.facebook as facebook

    def fake_parse(xml, parent_post_id=None, max_items=400):
        return [{"comment_key": "c-empty", "author": "Alice", "text": ""}], {
            "reason_code": "ok",
            "comments_returned": 1,
        }

    monkeypatch.setattr(facebook, "parse_fb_comments_from_xml_with_diagnostic", fake_parse)

    exec_ = _FakeExecutor(xml=_sheet_xml())
    context = {
        "comment_scroll_passes": 0,
        "open_post_press_back_after_extract": True,
    }
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert snapshots
    assert exec_.press_back_calls == 1
    assert context["comment_sheet_closed_after_extract"] is True
    assert context["comment_sheet_back_without_valid_comments"] is True
    assert context["agent_boot_preparsed_comments"] is True
    assert context["_preparsed_fb_comment_items"] == []
    assert context["_preparsed_fb_comment_diagnostic"]["comments_returned"] == 0
    assert context["_preparsed_fb_comment_diagnostic"]["dropped_empty_comments"] == 1


@pytest.mark.asyncio
async def test_collect_fb_comments_auto_back_requires_comment_sheet() -> None:
    exec_ = _FakeExecutor(xml=_SAMPLE_XML)
    context = {
        "comment_scroll_passes": 0,
        "open_post_press_back_after_extract": True,
    }
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert snapshots
    assert exec_.press_back_calls == 0
    assert "comment_sheet_closed_after_extract" not in context


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
async def test_comment_scroll_lifts_low_wall_cap_when_post_count_requires_budget(monkeypatch) -> None:
    from relay.tests.test_comment_filter import _sheet_xml
    from relay.tests.test_fb_action_bar_stats import ACTION_BAR_SNIPPET

    action_bar = (
        ACTION_BAR_SNIPPET.replace('text="23"', 'text="196"')
        .replace('content-desc="23"', 'content-desc="196"')
    )
    sheet = _sheet_xml().replace(
        '<node class="android.widget.Button" text="Đóng"',
        f"{action_bar}<node class=\"android.widget.Button\" text=\"Đóng\"",
    )

    parse_calls = 0

    def fake_parse(xml, parent_post_id=None, max_items=50):
        nonlocal parse_calls
        parse_calls += 1
        return [
            {
                "author": f"user-{parse_calls}",
                "text": f"comment body {parse_calls}",
                "comment_key": f"ck-{parse_calls}",
            }
        ], {"reason_code": "ok"}

    monkeypatch.setattr(
        "relay.extra_data.parsers.facebook.comment_pipeline.parse_fb_comments_from_xml_with_diagnostic",
        fake_parse,
    )

    class _RotatingSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=sheet)
            self._n = 0

        async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = sheet.replace('rotation="0"', f'rotation="{self._n}"')
            return await super().run_batch(serial, actions, early_exit=early_exit)

    context = {
        "max_items": 220,
        "comment_scroll_passes": 18,
        "comment_swipes_per_dump": 3,
        "comment_scroll_wall_s": 0.0001,
        "comment_scroll_pause_s": 0,
        "comment_scroll_settle_s": 0,
        "comment_large_target_fast_scroll": True,
        "comment_target_comments_per_swipe": 4,
        "comment_recover_chrome": False,
        "comment_no_growth_break": 0,
        "comment_stop_if_no_new": False,
        "stop_if_no_new": False,
        "min_comment_scan_passes": 0,
    }
    exec_ = _RotatingSheetExecutor()
    snapshots, err = await collect_xml_snapshots(exec_, "dev1", "fb_comments", context)

    assert err is None
    swipe_actions = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") in {"swipe", "u2_swipe_batch"}
    ]
    total_swipes = sum(
        int(action.get("count") or 0)
        if action.get("op") == "u2_swipe_batch"
        else 1
        for action in swipe_actions
    )
    assert total_swipes == 49
    u2_batches = [
        action for action in swipe_actions if action.get("op") == "u2_swipe_batch"
    ]
    assert u2_batches
    assert u2_batches[0]["count"] == 6
    assert u2_batches[0]["duration"] == pytest.approx(0.08)
    assert context["post_comment_count"] == 196
    assert context["comment_target_effective"] == 196
    assert context["comment_scroll_passes_configured"] == 18
    assert context["comment_scroll_passes_effective"] == 49
    assert context["comment_swipes_per_dump_configured"] == 3
    assert context["comment_swipes_per_dump_effective"] == 6
    assert context["comment_scroll_driver"] == "u2_http_batch"
    assert context["comment_scroll_wall_s_effective"] > context["comment_scroll_wall_s"]
    assert len(snapshots) == 10
    scroll_batches = [
        batch
        for batch in exec_.batches
        if any(action.get("op") in {"swipe", "u2_swipe_batch"} for action in batch)
    ]
    assert scroll_batches
    assert all(batch[-1].get("op") == "dump_hierarchy" for batch in scroll_batches)


@pytest.mark.asyncio
async def test_comment_scroll_honors_stop_if_no_new_alias() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    class _GrowingSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=_sheet_xml())
            self._n = 0

        async def run_batch(
            self,
            serial: str,
            actions: list[dict],
            early_exit: bool = True,
        ) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = _sheet_xml().replace(
                    'rotation="0"',
                    f'rotation="{self._n}"',
                )
            return await super().run_batch(serial, actions, early_exit=early_exit)

    exec_ = _GrowingSheetExecutor()
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {
            "comment_scroll_passes": 5,
            "comment_swipes_per_dump": 1,
            "comment_scroll_pause_s": 0,
            "min_comment_scan_passes": 1,
            "no_new_threshold": 1,
            "stop_if_no_new": False,
        },
    )
    assert err is None
    assert len(snapshots) >= 4


@pytest.mark.asyncio
async def test_comment_scroll_no_new_waits_when_probe_finds_no_comment_keys() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    class _GrowingEmptySheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=_sheet_xml())
            self._n = 0

        async def run_batch(
            self,
            serial: str,
            actions: list[dict],
            early_exit: bool = True,
        ) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = _sheet_xml().replace(
                    'rotation="0"',
                    f'rotation="{self._n}"',
                )
            return await super().run_batch(serial, actions, early_exit=early_exit)

    exec_ = _GrowingEmptySheetExecutor()
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {
            "comment_scroll_passes": 5,
            "comment_swipes_per_dump": 1,
            "comment_scroll_pause_s": 0,
            "comment_stop_if_no_new": True,
            "comment_no_new_threshold": 1,
            "min_comment_scan_passes": 1,
        },
    )

    assert err is None
    assert len(snapshots) >= 4


@pytest.mark.asyncio
async def test_comment_scroll_no_growth_is_disabled_unless_user_sets_break() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    context = {
        "comment_scroll_passes": 5,
        "comment_swipes_per_dump": 1,
        "comment_scroll_pause_s": 0,
        "comment_scroll_settle_s": 0,
        "comment_recover_chrome": False,
    }
    exec_ = _FakeExecutor(xml=_sheet_xml())

    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    swipes = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "swipe"
    ]
    assert len(swipes) == 5
    assert context["comment_scroll_passes_effective"] == 5
    assert len(snapshots) == 1


@pytest.mark.asyncio
async def test_comment_scroll_stops_when_post_comment_target_reached(monkeypatch) -> None:
    from relay.tests.test_comment_filter import _sheet_xml
    from relay.tests.test_fb_action_bar_stats import ACTION_BAR_SNIPPET

    action_bar = (
        ACTION_BAR_SNIPPET.replace('text="23"', 'text="3"')
        .replace('content-desc="23"', 'content-desc="3"')
    )
    sheet = _sheet_xml().replace(
        '<node class="android.widget.Button" text="Đóng"',
        f"{action_bar}<node class=\"android.widget.Button\" text=\"Đóng\"",
    )

    parse_calls = 0

    def fake_parse(xml, parent_post_id=None, max_items=50):
        nonlocal parse_calls
        parse_calls += 1
        comments = [
            {
                "author": f"user-{i}",
                "text": f"comment body {i}",
                "comment_key": f"ck-{i}",
            }
            for i in range(min(parse_calls, 3))
        ]
        return comments, {"reason_code": "ok"}

    monkeypatch.setattr(
        "relay.extra_data.parsers.facebook.comment_pipeline.parse_fb_comments_from_xml_with_diagnostic",
        fake_parse,
    )

    class _RotatingSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=sheet)
            self._n = 0

        async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = sheet.replace('rotation="0"', f'rotation="{self._n}"')
            return await super().run_batch(serial, actions, early_exit=early_exit)

    exec_ = _RotatingSheetExecutor()
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {
            "max_items": 500,
            "comment_scroll_passes": 20,
            "comment_swipes_per_dump": 1,
            "comment_scroll_pause_s": 0,
            "min_comment_scan_passes": 0,
            "comment_recover_chrome": False,
            "comment_no_growth_break": 0,
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
    assert len(swipes) <= 3
    assert parse_calls >= 3


@pytest.mark.asyncio
async def test_comment_scroll_auto_anchored_coverage_when_requested_exceeds_small_post_count(monkeypatch) -> None:
    from relay.tests.test_comment_filter import _sheet_xml
    from relay.tests.test_fb_action_bar_stats import ACTION_BAR_SNIPPET

    action_bar = (
        ACTION_BAR_SNIPPET.replace('text="23"', 'text="5"')
        .replace('content-desc="23"', 'content-desc="5"')
    )
    sheet = _sheet_xml().replace(
        '<node class="android.widget.Button" text="Đóng"',
        f"{action_bar}<node class=\"android.widget.Button\" text=\"Đóng\"",
    )

    parse_calls = 0

    def fake_parse(xml, parent_post_id=None, max_items=50):
        nonlocal parse_calls
        parse_calls += 1
        visible = min(parse_calls + 1, 5)
        start = max(1, visible - 2)
        comments = [
            {
                "author": f"user-{i}",
                "text": f"comment body {i}",
                "comment_key": f"ck-{i}",
            }
            for i in range(start, visible + 1)
        ]
        return comments, {"reason_code": "ok"}

    monkeypatch.setattr(
        "relay.extra_data.parsers.facebook.comment_pipeline.parse_fb_comments_from_xml_with_diagnostic",
        fake_parse,
    )

    class _RotatingSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=sheet)
            self._n = 0

        async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = sheet.replace('rotation="0"', f'rotation="{self._n}"')
            return await super().run_batch(serial, actions, early_exit=early_exit)

    context = {
        "max_items": 500,
        "comment_scroll_passes": 20,
        "comment_swipes_per_dump": 4,
        "comment_scroll_pause_s": 0,
        "comment_scroll_settle_s": 0,
        "comment_recover_chrome": False,
        "comment_no_growth_break": 0,
        "min_comment_scan_passes": 0,
        "comment_press_back_on_target": True,
    }
    exec_ = _RotatingSheetExecutor()

    snapshots, err = await collect_xml_snapshots(exec_, "dev1", "fb_comments", context)

    assert err is None
    assert snapshots
    assert context["post_comment_count"] == 5
    assert context["comment_target_effective"] == 5
    assert context["comment_crawl_mode_effective"] == "anchored_coverage"
    assert context["comment_scroll_stopped_reason"] == "target_reached"
    assert context["comment_coverage_collected"] == 5
    assert context["comment_target_back_pressed"] is True
    assert exec_.press_back_calls == 1

    coverage_batches = [
        batch
        for batch in exec_.batches
        if any(action.get("op") == "swipe" for action in batch)
    ]
    assert coverage_batches
    assert all(
        [action.get("op") for action in batch] == ["swipe", "dump_hierarchy"]
        for batch in coverage_batches
    )
    ledger = context["comment_coverage_ledger"]
    assert ledger[0]["phase"] == "initial"
    assert ledger[-1]["total"] == 5
    assert all(entry["overlap"] for entry in ledger if entry["phase"] == "coverage")


@pytest.mark.asyncio
async def test_comment_scroll_strict_500_target_scales_coverage_snapshot_budget(
    monkeypatch,
) -> None:
    from relay.tests.test_comment_filter import _sheet_xml
    from relay.tests.test_fb_action_bar_stats import ACTION_BAR_SNIPPET

    action_bar = (
        ACTION_BAR_SNIPPET.replace('text="23"', 'text="269"')
        .replace('content-desc="23"', 'content-desc="269"')
    )
    sheet = _sheet_xml().replace(
        '<node class="android.widget.Button" text="Đóng"',
        f"{action_bar}<node class=\"android.widget.Button\" text=\"Đóng\"",
    )

    def fake_parse(xml, parent_post_id=None, max_items=50):
        comments = [
            {
                "author": f"user-{i}",
                "text": f"comment body {i}",
                "comment_key": f"ck-{i}",
            }
            for i in range(3)
        ]
        return comments, {"reason_code": "ok"}

    monkeypatch.setattr(
        "relay.extra_data.parsers.facebook.comment_pipeline.parse_fb_comments_from_xml_with_diagnostic",
        fake_parse,
    )

    class _RotatingSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=sheet)
            self._n = 0

        async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = sheet.replace('rotation="0"', f'rotation="{self._n}"')
            return await super().run_batch(serial, actions, early_exit=early_exit)

    context = {
        "max_items": 500,
        "comment_scroll_passes": 269,
        "comment_swipes_per_dump": 1,
        "comment_max_snapshots": 10,
        "comment_scroll_pause_s": 0,
        "comment_scroll_settle_s": 0,
        "comment_recover_chrome": False,
        "comment_target_budget": False,
        "comment_require_complete": True,
        "comment_auto_coverage_target_max": 500,
        "comment_no_growth_break": 0,
        "min_comment_scan_passes": 0,
    }

    snapshots, err = await collect_xml_snapshots(
        _RotatingSheetExecutor(),
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert snapshots
    assert context["post_comment_count"] == 269
    assert context["comment_target_effective"] == 269
    assert context["comment_crawl_mode_effective"] == "anchored_coverage"
    assert context["comment_max_snapshots_effective"] == 270
    assert context["comment_scroll_stopped_reason"] == "coverage_tail_no_new"
    assert context["comment_coverage_collected"] == 3


@pytest.mark.asyncio
async def test_comment_scroll_records_batched_budget_exhaustion(monkeypatch) -> None:
    from relay.tests.test_comment_filter import _sheet_xml
    from relay.tests.test_fb_action_bar_stats import ACTION_BAR_SNIPPET

    action_bar = (
        ACTION_BAR_SNIPPET.replace('text="23"', 'text="600"')
        .replace('content-desc="23"', 'content-desc="600"')
    )
    sheet = _sheet_xml().replace(
        '<node class="android.widget.Button" text="Đóng"',
        f"{action_bar}<node class=\"android.widget.Button\" text=\"Đóng\"",
    )
    monkeypatch.setattr(
        "relay.extra_data.parsers.facebook.comment_pipeline.parse_fb_comments_from_xml_with_diagnostic",
        lambda xml, **kwargs: (
            [{"author": "Alice", "text": "Hello", "comment_key": "comment-1"}],
            {"reason_code": "ok"},
        ),
    )

    class _RotatingSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=sheet)
            self._n = 0

        async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = sheet.replace('rotation="0"', f'rotation="{self._n}"')
            return await super().run_batch(serial, actions, early_exit=early_exit)

    context = {
        "max_items": 600,
        "comment_scroll_passes": 2,
        "comment_swipes_per_dump": 1,
        "comment_scroll_pause_s": 0,
        "comment_scroll_settle_s": 0,
        "comment_recover_chrome": False,
        "comment_target_budget": False,
        "comment_crawl_mode": "batched",
        "comment_no_growth_break": 0,
        "min_comment_scan_passes": 0,
    }

    snapshots, err = await collect_xml_snapshots(
        _RotatingSheetExecutor(),
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert snapshots
    assert context["comment_crawl_mode_effective"] == "batched_tail_probe"
    assert context["comment_scroll_stopped_reason"] == "swipe_budget_exhausted"


@pytest.mark.asyncio
async def test_comment_scroll_skips_when_post_comment_count_is_zero() -> None:
    from relay.tests.test_comment_filter import _sheet_xml
    from relay.tests.test_fb_action_bar_stats import ACTION_BAR_SNIPPET

    zero_action_bar = (
        ACTION_BAR_SNIPPET
        .replace('text="23"', 'text="0"')
        .replace('content-desc="23"', 'content-desc="0"')
    )
    sheet = _sheet_xml().replace(
        '<node class="android.widget.Button" text="Đóng"',
        f"{zero_action_bar}<node class=\"android.widget.Button\" text=\"Đóng\"",
    )
    context = {
        "comment_scroll_passes": 20,
        "comment_swipes_per_dump": 1,
        "comment_scroll_pause_s": 0,
    }
    exec_ = _FakeExecutor(xml=sheet)

    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert snapshots == [sheet]
    assert context["post_comment_count"] == 0
    assert context["comment_target_effective"] == 0
    assert context["comment_scroll_skipped_reason"] == "post_comment_count_zero"
    swipes = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "swipe"
    ]
    assert swipes == []


@pytest.mark.asyncio
async def test_comment_scroll_skips_when_comment_sheet_action_bar_has_no_comment_badge() -> None:
    from relay.tests.test_comment_filter import _sheet_xml
    from relay.tests.test_fb_action_bar_stats import ACTION_BAR_NO_COMMENT_COUNT_SNIPPET

    sheet = _sheet_xml().replace(
        '<node package="com.facebook.katana" clickable="true" bounds="[40,180][680,260]"',
        f"{ACTION_BAR_NO_COMMENT_COUNT_SNIPPET}"
        '<node package="com.facebook.katana" clickable="true" bounds="[40,180][680,260]"',
    )
    context = {
        "comment_scroll_passes": 20,
        "comment_swipes_per_dump": 1,
        "comment_scroll_pause_s": 0,
    }
    exec_ = _FakeExecutor(xml=sheet)

    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert snapshots == [sheet]
    assert context["post_comment_count"] == 0
    assert context["comment_scroll_skipped_reason"] == "post_comment_count_zero"
    swipes = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "swipe"
    ]
    assert swipes == []


@pytest.mark.asyncio
async def test_comment_scroll_does_not_skip_when_comment_count_is_unknown() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    sheet = _sheet_xml()
    context = {
        "comment_scroll_passes": 3,
        "comment_swipes_per_dump": 1,
        "comment_no_growth_break": 0,
        "comment_stop_if_no_new": False,
        "stop_if_no_new": False,
        "comment_scroll_pause_s": 0,
        "comment_recover_chrome": False,
    }
    exec_ = _FakeExecutor(xml=sheet)

    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert snapshots
    assert context["post_comment_count"] is None
    swipes = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "swipe"
    ]
    assert len(swipes) == 3


@pytest.mark.asyncio
async def test_comment_scroll_keeps_requested_budget_when_count_unknown() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    sheet = _sheet_xml()

    class _RotatingSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=sheet)
            self._n = 0

        async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = sheet.replace('rotation="0"', f'rotation="{self._n}"')
            return await super().run_batch(serial, actions, early_exit=early_exit)

    context = {
        "max_items": 220,
        "comment_scroll_passes": 18,
        "comment_swipes_per_dump": 3,
        "comment_scroll_wall_s": 16,
        "comment_hard_budget": True,
        "comment_scroll_pause_s": 0,
        "comment_scroll_settle_s": 0,
        "comment_recover_chrome": False,
        "comment_no_growth_break": 0,
        "comment_stop_if_no_new": False,
        "stop_if_no_new": False,
        "min_comment_scan_passes": 0,
    }
    exec_ = _RotatingSheetExecutor()

    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert snapshots
    swipe_actions = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") in {"swipe", "u2_swipe_batch"}
    ]
    total_swipes = sum(
        int(action.get("count") or 0)
        if action.get("op") == "u2_swipe_batch"
        else 1
        for action in swipe_actions
    )
    assert context["post_comment_count"] is None
    assert context["comment_target_effective"] == 220
    assert context["comment_target_source"] == "max_items"
    assert "comment_scroll_passes_configured" not in context
    assert context["comment_scroll_passes_effective"] == 18
    assert context["comment_scroll_wall_s_effective"] == 16
    assert total_swipes == 18


@pytest.mark.asyncio
async def test_comment_scroll_uses_requested_target_for_large_visible_post_count() -> None:
    from relay.tests.test_comment_filter import _sheet_xml
    from relay.tests.test_fb_action_bar_stats import ACTION_BAR_SNIPPET

    action_bar = (
        ACTION_BAR_SNIPPET
        .replace('text="23"', 'text="500"')
        .replace('content-desc="23"', 'content-desc="500"')
    )
    sheet = _sheet_xml().replace(
        '<node package="com.facebook.katana" clickable="true" bounds="[40,180][680,260]"',
        f"{action_bar}"
        '<node package="com.facebook.katana" clickable="true" bounds="[40,180][680,260]"',
    )

    class _RotatingSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=sheet)
            self._n = 0

        async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = sheet.replace('rotation="0"', f'rotation="{self._n}"')
            return await super().run_batch(serial, actions, early_exit=early_exit)

    context = {
        "max_items": 500,
        "comment_scroll_passes": 16,
        "comment_swipes_per_dump": 6,
        "comment_max_snapshots": 10,
        "comment_scroll_wall_s": 16,
        "comment_scroll_pause_s": 0,
        "comment_scroll_settle_s": 0,
        "comment_recover_chrome": False,
        "comment_no_growth_break": 0,
        "comment_stop_if_no_new": False,
        "stop_if_no_new": False,
        "min_comment_scan_passes": 0,
    }
    exec_ = _RotatingSheetExecutor()

    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert snapshots
    swipe_actions = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") in {"swipe", "u2_swipe_batch"}
    ]
    total_swipes = sum(
        int(action.get("count") or 0)
        if action.get("op") == "u2_swipe_batch"
        else 1
        for action in swipe_actions
    )
    assert context["post_comment_count"] == 500
    assert context["max_items"] == 500
    assert context["comment_target_effective"] == 500
    assert context["comment_target_source"] == "post_count"
    assert context["comment_scroll_passes_configured"] == 16
    assert context["comment_scroll_passes_effective"] == 500
    assert context["comment_scroll_wall_s_effective"] > 16
    assert total_swipes == 500
    assert len(snapshots) > 10


@pytest.mark.asyncio
async def test_comment_scroll_hard_budget_keeps_max_items_below_visible_post_count() -> None:
    from relay.tests.test_comment_filter import _sheet_xml
    from relay.tests.test_fb_action_bar_stats import ACTION_BAR_SNIPPET

    action_bar = (
        ACTION_BAR_SNIPPET
        .replace('text="23"', 'text="500"')
        .replace('content-desc="23"', 'content-desc="500"')
    )
    sheet = _sheet_xml().replace(
        '<node package="com.facebook.katana" clickable="true" bounds="[40,180][680,260]"',
        f"{action_bar}"
        '<node package="com.facebook.katana" clickable="true" bounds="[40,180][680,260]"',
    )
    context = {
        "max_items": 220,
        "comment_scroll_passes": 16,
        "comment_swipes_per_dump": 6,
        "comment_max_snapshots": 10,
        "comment_scroll_wall_s": 16,
        "comment_hard_budget": True,
        "comment_scroll_pause_s": 0,
    }

    snapshots, err = await collect_xml_snapshots(
        _FakeExecutor(xml=sheet),
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert snapshots
    assert context["post_comment_count"] == 500
    assert context["max_items"] == 220
    assert context["comment_target_effective"] == 220
    assert "comment_target_lifted_from_post_count" not in context


@pytest.mark.asyncio
async def test_comment_scroll_lifts_cap_when_only_max_items_is_explicit() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    sheet = _sheet_xml()

    class _RotatingSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=sheet)
            self._n = 0

        async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = sheet.replace('rotation="0"', f'rotation="{self._n}"')
            return await super().run_batch(serial, actions, early_exit=early_exit)

    context = {
        "max_items": 120,
        "comment_swipes_per_dump": 3,
        "comment_scroll_wall_s": 16,
        "comment_target_budget_unknown_count": True,
        "comment_scroll_pause_s": 0,
        "comment_scroll_settle_s": 0,
        "comment_recover_chrome": False,
        "comment_no_growth_break": 0,
        "comment_stop_if_no_new": False,
        "stop_if_no_new": False,
        "min_comment_scan_passes": 0,
    }
    exec_ = _RotatingSheetExecutor()

    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert snapshots
    swipes = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "swipe"
    ]
    assert context["post_comment_count"] is None
    assert context["comment_target_effective"] == 120
    assert context["comment_target_source"] == "max_items"
    assert context["comment_scroll_passes_configured"] == 4
    assert context["comment_scroll_passes_effective"] == 120
    assert context["comment_scroll_wall_s_effective"] > 16
    assert len(swipes) == 120


@pytest.mark.asyncio
async def test_comment_scroll_unknown_count_stops_when_max_items_target_seen(monkeypatch) -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    sheet = _sheet_xml()

    parse_calls = 0

    def fake_parse(xml, parent_post_id=None, max_items=50):
        nonlocal parse_calls
        parse_calls += 1
        count = 50 if parse_calls == 1 else 120
        return [
            {
                "author": f"user-{idx}",
                "text": f"comment body {idx}",
                "comment_key": f"ck-{idx}",
            }
            for idx in range(count)
        ], {"reason_code": "ok"}

    monkeypatch.setattr(
        "relay.extra_data.parsers.facebook.comment_pipeline.parse_fb_comments_from_xml_with_diagnostic",
        fake_parse,
    )

    class _RotatingSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=sheet)
            self._n = 0

        async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = sheet.replace('rotation="0"', f'rotation="{self._n}"')
            return await super().run_batch(serial, actions, early_exit=early_exit)

    context = {
        "max_items": 100,
        "comment_scroll_passes": 40,
        "comment_swipes_per_dump": 3,
        "comment_scroll_wall_s": 16,
        "comment_scroll_pause_s": 0,
        "comment_scroll_settle_s": 0,
        "comment_recover_chrome": False,
        "comment_no_growth_break": 0,
        "comment_stop_if_no_new": False,
        "stop_if_no_new": False,
        "min_comment_scan_passes": 0,
    }
    exec_ = _RotatingSheetExecutor()

    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert snapshots
    swipes = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "swipe"
    ]
    assert context["post_comment_count"] is None
    assert context["comment_target_source"] == "max_items"
    assert len(swipes) == 3


@pytest.mark.asyncio
async def test_comment_scroll_honors_explicit_budget_above_legacy_cap() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    class _RotatingSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=_sheet_xml())
            self._n = 0

        async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = _sheet_xml().replace('rotation="0"', f'rotation="{self._n}"')
            return await super().run_batch(serial, actions, early_exit=early_exit)

    exec_ = _RotatingSheetExecutor()
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {
            "comment_scroll_passes": 120,
            "comment_swipes_per_dump": 6,
            "comment_no_growth_break": 0,
            "comment_stop_if_no_new": False,
            "stop_if_no_new": False,
            "min_comment_scan_passes": 0,
            "comment_recover_chrome": False,
        },
    )

    assert err is None
    assert len(snapshots) == 21
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
    assert len(swipes) == 120
    assert len(dumps) == 21


@pytest.mark.asyncio
async def test_comment_scroll_raises_stale_snapshot_cap_for_explicit_budget() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    class _RotatingSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=_sheet_xml())
            self._n = 0

        async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = _sheet_xml().replace('rotation="0"', f'rotation="{self._n}"')
            return await super().run_batch(serial, actions, early_exit=early_exit)

    exec_ = _RotatingSheetExecutor()
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {
            "comment_scroll_passes": 120,
            "comment_swipes_per_dump": 4,
            "comment_max_snapshots": 12,
            "comment_no_growth_break": 0,
            "comment_stop_if_no_new": False,
            "stop_if_no_new": False,
            "min_comment_scan_passes": 0,
            "comment_recover_chrome": False,
        },
    )

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
    assert err is None
    assert len(snapshots) == 31
    assert len(swipes) == 120
    assert len(dumps) == 31


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
    with patch("asyncio.sleep") as sleep_mock:
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
    click_batch = next(batch for batch in exec_.batches if batch[0].get("op") == "click")
    assert [action["op"] for action in click_batch] == [
        "click",
        "sleep",
        "dump_hierarchy",
    ]
    sleep_mock.assert_not_called()


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
async def test_collect_fb_comments_default_fast_timing_preserves_requested_budget() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    class _GrowingSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=_sheet_xml())
            self._n = 0

        async def run_batch(
            self,
            serial: str,
            actions: list[dict],
            early_exit: bool = True,
        ) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = _sheet_xml().replace(
                    'rotation="0"',
                    f'rotation="{self._n}"',
                )
            return await super().run_batch(serial, actions, early_exit=early_exit)

    context = {
        "max_items": 500,
        "comment_scroll_passes": 5,
        "comment_swipes_per_dump": 1,
        "comment_no_growth_break": 0,
        "min_comment_scan_passes": 0,
        "comment_max_snapshots": 10,
        "comment_scroll_wall_s": 0,
        "comment_scroll_duration_ms": 300,
        "comment_scroll_pause_s": 0.001,
        "comment_scroll_settle_s": 0.002,
        "comment_recover_chrome": False,
        "comment_stop_if_no_new": False,
        "stop_if_no_new": False,
    }
    exec_ = _GrowingSheetExecutor()

    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        context,
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
    assert len(swipes) == 5
    assert len(dumps) == 6
    assert {action["duration"] for action in swipes} == {0.3}
    assert not any(str(key).startswith("comment_fast") for key in context)
    assert context["comment_target_effective"] == 500


@pytest.mark.asyncio
async def test_collect_fb_comments_large_xml_honors_explicit_budget() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    payload = '<node class="android.widget.TextView" text="' + ("x" * (640 * 1024)) + '" />'

    def _big_sheet(n: int) -> str:
        return _sheet_xml().replace(
            "</hierarchy>",
            f'<node text="rotation-{n}" />{payload}</hierarchy>',
        )

    class _LargeSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=_big_sheet(0))
            self._n = 0

        async def run_batch(
            self,
            serial: str,
            actions: list[dict],
            early_exit: bool = True,
        ) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = _big_sheet(self._n)
            return await super().run_batch(serial, actions, early_exit=early_exit)

    exec_ = _LargeSheetExecutor()
    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        {
            "comment_scroll_passes": 120,
            "comment_swipes_per_dump": 6,
            "comment_no_growth_break": 0,
            "comment_stop_if_no_new": False,
            "stop_if_no_new": False,
            "min_comment_scan_passes": 0,
            "comment_recover_chrome": False,
        },
    )

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
    assert err is None
    assert len(snapshots) == 21
    assert len(swipes) == 120
    assert len(dumps) == 21


@pytest.mark.asyncio
async def test_collect_fb_comments_deep_scroll_context_keeps_requested_budget() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    class _GrowingSheetExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=_sheet_xml())
            self._n = 0

        async def run_batch(
            self,
            serial: str,
            actions: list[dict],
            early_exit: bool = True,
        ) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = _sheet_xml().replace(
                    'rotation="0"',
                    f'rotation="{self._n}"',
                )
            return await super().run_batch(serial, actions, early_exit=early_exit)

    context = {
        "max_items": 500,
        "comment_scroll_passes": 40,
        "comment_swipes_per_dump": 1,
        "comment_no_growth_break": 0,
        "min_comment_scan_passes": 3,
        "comment_max_snapshots": 50,
        "comment_scroll_wall_s": 0,
        "comment_scroll_pause_s": 0,
        "comment_recover_chrome": False,
        "comment_stop_if_no_new": False,
        "stop_if_no_new": False,
    }
    exec_ = _GrowingSheetExecutor()

    snapshots, err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        context,
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
    assert len(swipes) == 40
    assert len(dumps) == 41
    assert context["comment_target_effective"] == 500
    assert not any(str(key).startswith("comment_fast") for key in context)


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
            {
                "post_tap_wait_s": 0.0,
                "comment_target_verify": False,
                "comment_target_tap_enabled": True,
            },
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
    assert exec_.clicks == [(308, 230)]


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
    assert exec_.clicks == [(308, 230)]
    assert exec_.batches[0][0]["op"] == "click_spec"
    assert exec_.batches[0][0]["timeout"] == 0.25


@pytest.mark.asyncio
async def test_collect_fb_comment_target_tap_disabled_by_default() -> None:
    exec_ = _SessionFakeExecutor()
    diagnostic = {
        "reason_code": "ok",
        "target": {"bounds": [100, 200, 300, 250]},
        "alternates": [],
    }
    with patch(
        "relay.extra_data.ingest._parse_items",
        return_value=([], diagnostic),
    ):
        snapshots, err, tapped, diagnostic = await collect_fb_comment_target_with_tap(
            exec_,
            "dev1",
            {"post_tap_wait_s": 0.0},
        )

    assert err is None
    assert tapped is False
    assert snapshots == [_SAMPLE_XML]
    assert exec_.clicks == []
    assert diagnostic["tap_disabled"] is True
    assert diagnostic["target"] is None
    assert diagnostic["resolved_target"] == {"bounds": [100, 200, 300, 250]}
    assert diagnostic["verify_attempts"][0]["reason"] == "comment_target_tap_disabled"


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
            {"post_tap_wait_s": 0.0, "comment_target_tap_enabled": True},
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
                "comment_target_tap_enabled": True,
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
                "comment_target_tap_enabled": True,
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
            {
                "post_tap_wait_s": 0.0,
                "comment_target_verify": False,
                "comment_target_tap_enabled": True,
            },
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

    with patch(
        "relay.extra_data.ingest._parse_items",
        side_effect=_fake_parse,
    ), patch("asyncio.sleep") as sleep_mock:
        report, err = await collect_fb_comment_filter_apply(
            exec_,
            "dev1",
            {"comment_filter": "all_comments"},
        )
    assert err is None
    assert report["switched"] is True
    assert report["reason_code"] == "already_on_filter"
    assert len(report["steps"]) == 3
    assert report["total_ms"] >= 0
    assert report["dump_ms"] >= 0
    assert report["parse_ms"] >= 0
    assert report["click_ms"] >= 0
    assert report["sleep_ms"] >= 0
    assert report["wait_ms"] >= 0
    assert report["state_verified"] is True
    assert report["steps"][0]["dump_ms"] >= 0
    assert report["steps"][0]["parse_ms"] >= 0
    assert report["steps"][0]["click_ms"] >= 0
    assert exec_.clicks == [(20, 30), (360, 1080)]
    assert exec_.session_scope_calls == 1
    sleep_mock.assert_not_called()
    click_batches = [
        batch for batch in exec_.batches
        if batch and batch[0].get("op") == "click"
    ]
    assert click_batches[0][1]["op"] == "wait_exists"
    assert click_batches[1][1]["op"] == "wait_gone"


@pytest.mark.asyncio
async def test_comment_filter_wait_error_still_verifies_successful_tap() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    class _WaitErrorExecutor(_SessionFakeExecutor):
        async def run_batch(
            self,
            serial: str,
            actions: list[dict],
            early_exit: bool = True,
        ) -> dict:
            if len(actions) == 2 and actions[0].get("op") == "click":
                self._ui_generations[serial] = self.ui_generation(serial) + 1
                self.batches.append(actions)
                self.clicks.append((int(actions[0]["x"]), int(actions[0]["y"])))
                return {
                    "ok": False,
                    "results": [
                        {"op": "click", "ok": True, "duration_ms": 1.0},
                        {
                            "op": actions[1]["op"],
                            "ok": False,
                            "error": "transport error",
                            "duration_ms": 2.0,
                        },
                    ],
                    "error": "action[1] wait failed",
                }
            return await super().run_batch(serial, actions, early_exit=early_exit)

    exec_ = _WaitErrorExecutor(xml=_sheet_xml())
    phases = iter([
        {
            "phase": "select_option",
            "reason_code": "select_filter",
            "tap": {"bounds": [10, 20, 30, 40]},
        },
        {
            "phase": "done",
            "reason_code": "already_on_filter",
            "tap": None,
        },
    ])

    with patch(
        "relay.extra_data.ingest._parse_items",
        side_effect=lambda *_args: ([], next(phases)),
    ):
        report, err = await collect_fb_comment_filter_apply(
            exec_,
            "dev-wait-error",
            {
                "context_id": "exec-wait-error",
                "parent_id": "parent-wait-error",
                "comment_filter": "newest",
            },
        )

    assert err is None
    assert report["state_verified"] is True
    assert report["reason_code"] == "already_on_filter"
    assert report["steps"][0]["state_wait_hit"] is False
    assert len([
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "dump_hierarchy"
    ]) == 2


@pytest.mark.asyncio
async def test_fb_comments_reuses_verified_filter_hierarchy_once() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    exec_ = _SessionFakeExecutor(xml=_sheet_xml())
    handoff_context = {
        "context_id": "exec-handoff",
        "parent_id": "parent-handoff",
        "comment_filter": "all_comments",
    }
    with patch(
        "relay.extra_data.ingest._parse_items",
        return_value=(
            [],
            {
                "phase": "done",
                "reason_code": "already_on_filter",
                "tap": None,
            },
        ),
    ):
        report, err = await collect_fb_comment_filter_apply(
            exec_,
            "dev1",
            dict(handoff_context),
        )

    comment_context = {
        **handoff_context,
        "comment_scroll_passes": 0,
        "require_verified_parent": True,
    }
    snapshots, collect_err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        comment_context,
    )

    dumps = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "dump_hierarchy"
    ]
    assert err is None
    assert collect_err is None
    assert report["state_verified"] is True
    assert snapshots == [_sheet_xml()]
    assert len(dumps) == 1
    assert comment_context["hierarchy_handoff_reused"] is True


@pytest.mark.asyncio
async def test_fb_comments_does_not_reuse_handoff_after_intervening_ui_action() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    exec_ = _SessionFakeExecutor(xml=_sheet_xml())
    handoff_context = {
        "context_id": "exec-interleaved",
        "parent_id": "parent-interleaved",
        "comment_filter": "all_comments",
    }
    with patch(
        "relay.extra_data.ingest._parse_items",
        return_value=(
            [],
            {
                "phase": "done",
                "reason_code": "already_on_filter",
                "tap": None,
            },
        ),
    ):
        _report, err = await collect_fb_comment_filter_apply(
            exec_,
            "dev-interleaved",
            dict(handoff_context),
        )

    await exec_.run_batch(
        "dev-interleaved",
        [{"op": "click", "x": 1, "y": 1}],
    )
    comment_context = {**handoff_context, "comment_scroll_passes": 0}
    _snapshots, collect_err = await collect_xml_snapshots(
        exec_,
        "dev-interleaved",
        "fb_comments",
        comment_context,
    )

    assert err is None
    assert collect_err is None
    assert "hierarchy_handoff_reused" not in comment_context
    assert len([
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "dump_hierarchy"
    ]) == 2


@pytest.mark.asyncio
async def test_filter_handoff_is_not_stored_when_ui_changes_during_final_dump() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    class _ConcurrentMutationExecutor(_SessionFakeExecutor):
        async def run_batch(
            self,
            serial: str,
            actions: list[dict],
            early_exit: bool = True,
        ) -> dict:
            changes_during_dump = any(
                action.get("op") == "dump_hierarchy"
                for action in actions
            )
            if changes_during_dump:
                self.begin_ui_mutation(serial)
            try:
                return await super().run_batch(
                    serial,
                    actions,
                    early_exit=early_exit,
                )
            finally:
                if changes_during_dump:
                    self.end_ui_mutation(serial)

    exec_ = _ConcurrentMutationExecutor(xml=_sheet_xml())
    handoff_context = {
        "context_id": "exec-concurrent-dump",
        "parent_id": "parent-concurrent-dump",
        "comment_filter": "all_comments",
    }
    with patch(
        "relay.extra_data.ingest._parse_items",
        return_value=(
            [],
            {
                "phase": "done",
                "reason_code": "already_on_filter",
                "tap": None,
            },
        ),
    ):
        report, err = await collect_fb_comment_filter_apply(
            exec_,
            "dev-concurrent-dump",
            dict(handoff_context),
        )

    comment_context = {**handoff_context, "comment_scroll_passes": 0}
    _snapshots, collect_err = await collect_xml_snapshots(
        exec_,
        "dev-concurrent-dump",
        "fb_comments",
        comment_context,
    )

    assert err is None
    assert collect_err is None
    assert report["state_verified"] is True
    assert report.get("hierarchy_handoff_stored") is not True
    assert "hierarchy_handoff_reused" not in comment_context
    assert len([
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "dump_hierarchy"
    ]) == 2


@pytest.mark.asyncio
async def test_fb_comments_does_not_reuse_expired_filter_handoff() -> None:
    from relay.extra_data import collector as collector_mod
    from relay.tests.test_comment_filter import _sheet_xml

    exec_ = _SessionFakeExecutor(xml=_sheet_xml())
    handoff_context = {
        "context_id": "exec-expired",
        "parent_id": "parent-expired",
        "comment_filter": "all_comments",
    }
    with patch.object(
        collector_mod,
        "_FILTER_HIERARCHY_HANDOFF_TTL_S",
        0.0,
    ), patch(
        "relay.extra_data.ingest._parse_items",
        return_value=(
            [],
            {
                "phase": "done",
                "reason_code": "already_on_filter",
                "tap": None,
            },
        ),
    ):
        _report, err = await collect_fb_comment_filter_apply(
            exec_,
            "dev-expired",
            dict(handoff_context),
        )

    comment_context = {**handoff_context, "comment_scroll_passes": 0}
    _snapshots, collect_err = await collect_xml_snapshots(
        exec_,
        "dev-expired",
        "fb_comments",
        comment_context,
    )

    assert err is None
    assert collect_err is None
    assert "hierarchy_handoff_reused" not in comment_context
    assert len([
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "dump_hierarchy"
    ]) == 2


@pytest.mark.asyncio
async def test_release_collect_lock_clears_handoff_even_while_lock_is_held() -> None:
    from relay.extra_data import collector as collector_mod
    from relay.tests.test_comment_filter import _sheet_xml

    exec_ = _SessionFakeExecutor(xml=_sheet_xml())
    handoff_context = {
        "context_id": "exec-offline",
        "parent_id": "parent-offline",
        "comment_filter": "all_comments",
    }
    with patch(
        "relay.extra_data.ingest._parse_items",
        return_value=(
            [],
            {
                "phase": "done",
                "reason_code": "already_on_filter",
                "tap": None,
            },
        ),
    ):
        _report, err = await collect_fb_comment_filter_apply(
            exec_,
            "dev-offline",
            dict(handoff_context),
        )

    lock = collector_mod._collect_lock("dev-offline")
    await lock.acquire()
    try:
        release_collect_lock("dev-offline")
    finally:
        lock.release()

    comment_context = {**handoff_context, "comment_scroll_passes": 0}
    _snapshots, collect_err = await collect_xml_snapshots(
        exec_,
        "dev-offline",
        "fb_comments",
        comment_context,
    )

    assert err is None
    assert collect_err is None
    assert "hierarchy_handoff_reused" not in comment_context


@pytest.mark.asyncio
async def test_fb_comments_does_not_reuse_filter_hierarchy_for_another_parent() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    exec_ = _SessionFakeExecutor(xml=_sheet_xml())
    with patch(
        "relay.extra_data.ingest._parse_items",
        return_value=(
            [],
            {
                "phase": "done",
                "reason_code": "already_on_filter",
                "tap": None,
            },
        ),
    ):
        _report, err = await collect_fb_comment_filter_apply(
            exec_,
            "dev1",
            {
                "context_id": "exec-parent-scope",
                "parent_id": "parent-a",
                "comment_filter": "all_comments",
            },
        )

    comment_context = {
        "context_id": "exec-parent-scope",
        "parent_id": "parent-b",
        "comment_filter": "all_comments",
        "comment_scroll_passes": 0,
        "require_verified_parent": True,
    }
    _snapshots, collect_err = await collect_xml_snapshots(
        exec_,
        "dev1",
        "fb_comments",
        comment_context,
    )

    dumps = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "dump_hierarchy"
    ]
    assert err is None
    assert collect_err is None
    assert len(dumps) == 2
    assert "hierarchy_handoff_reused" not in comment_context


@pytest.mark.asyncio
async def test_fb_comments_filter_hierarchy_handoff_is_consumed_once() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    exec_ = _SessionFakeExecutor(xml=_sheet_xml())
    handoff_context = {
        "context_id": "exec-one-shot",
        "parent_id": "parent-one-shot",
        "comment_filter": "newest",
    }
    with patch(
        "relay.extra_data.ingest._parse_items",
        return_value=(
            [],
            {
                "phase": "done",
                "reason_code": "already_on_filter",
                "tap": None,
            },
        ),
    ):
        _report, err = await collect_fb_comment_filter_apply(
            exec_,
            "dev1",
            dict(handoff_context),
        )

    first_context = {**handoff_context, "comment_scroll_passes": 0}
    second_context = {**handoff_context, "comment_scroll_passes": 0}
    _first, first_err = await collect_xml_snapshots(
        exec_, "dev1", "fb_comments", first_context
    )
    _second, second_err = await collect_xml_snapshots(
        exec_, "dev1", "fb_comments", second_context
    )

    dumps = [
        action
        for batch in exec_.batches
        for action in batch
        if action.get("op") == "dump_hierarchy"
    ]
    assert err is None
    assert first_err is None
    assert second_err is None
    assert first_context["hierarchy_handoff_reused"] is True
    assert "hierarchy_handoff_reused" not in second_context
    assert len(dumps) == 2


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
    assert diag["timing"]["total_ms"] >= 0
    assert diag["timing"]["resolve_ms"] >= 0
    assert diag["attempts"][0]["tap_dump_ms"] >= 0
    assert diag["attempts"][0]["verify_ms"] >= 0
    assert exec_.press_back_calls == 0
    assert diag.get("attempts") and diag["attempts"][0].get("back_pressed") is False


@pytest.mark.asyncio
async def test_open_post_rejects_changed_but_unverified_hierarchy() -> None:
    """A different XML tree is not enough evidence that the requested post opened."""
    exec_ = _SessionFakeExecutor()
    feed_xml = """<?xml version="1.0"?>
<hierarchy><node text="feed-post" bounds="[0,200][1080,2200]"/></hierarchy>"""
    changed_feed_xml = """<?xml version="1.0"?>
<hierarchy><node text="different-feed-post" bounds="[0,200][1080,2200]"/></hierarchy>"""
    exec_._dump_xml = changed_feed_xml
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
    assert diag["reason_code"] == "post_open_verify_failed"
    assert ctx.get("open_post_detail") is not True


@pytest.mark.asyncio
async def test_open_post_target_not_found_reports_timing_diagnostic() -> None:
    exec_ = _SessionFakeExecutor()
    feed_xml = """<?xml version="1.0"?>
<hierarchy>
  <node text="Nhóm công khai" bounds="[0,0][1080,100]"/>
  <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,200][1080,2200]"/>
</hierarchy>"""
    ctx: dict = {"open_post_before_extract": True, "post_open_verify": True}
    with patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline.resolve_post_open_targets_from_xml",
        return_value=(None, []),
    ), patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline.hierarchy_is_fb_post_detail_from_xml",
        return_value=False,
    ), patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline.diagnose_post_open_resolution",
        return_value={"post_count": 0, "reason": "no_header"},
    ):
        detail_xml, diag = await _maybe_open_fb_post_detail(
            exec_, "dev1", ctx, feed_xml
        )

    assert detail_xml is None
    assert diag["reason_code"] == "post_open_target_not_found"
    assert diag["candidate_count"] == 0
    assert diag["diagnostic"] == {"post_count": 0, "reason": "no_header"}
    assert diag["timing"]["total_ms"] >= 0
    assert diag["timing"]["resolve_ms"] >= 0
    assert diag["timing"]["diagnose_ms"] >= 0


@pytest.mark.asyncio
async def test_open_post_failed_overlay_does_not_back_out_of_group_feed() -> None:
    exec_ = _SessionFakeExecutor()
    feed_xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" text="Nhóm công khai" bounds="[40,120][400,180]" />
  <node package="com.facebook.katana" text="Bạn viết gì đi…" bounds="[40,220][900,280]" />
  <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,300][1080,2200]">
    <node bounds="[0,400][1080,1100]">
      <node text="Author" bounds="[132,420][420,464]"/>
      <node text="5 ngày" bounds="[132,468][280,504]" clickable="true"/>
    </node>
  </node>
</hierarchy>"""
    profile_overlay_xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" text="Trang cá nhân" bounds="[40,200][400,260]" />
</hierarchy>"""
    exec_._dump_xml = profile_overlay_xml
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

    assert detail_xml is None
    assert diag["reason_code"] == "post_open_verify_failed"
    assert ctx["_fb_group_navigation"] is True
    assert diag["attempts"][0]["back_pressed"] is False
    assert exec_.press_back_calls == 0


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
    assert diag["timing"]["total_ms"] >= 0
    assert diag["attempts"][0]["tap_dump_ms"] >= 0
    assert diag["attempts"][0]["verify_ms"] >= 0
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
async def test_open_post_default_batches_tap_sleep_and_dump() -> None:
    exec_ = _SessionFakeExecutor()
    feed_xml = """<?xml version="1.0"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,200][1080,2200]">
    <node bounds="[0,400][1080,1100]">
      <node text="Author" bounds="[132,420][420,464]"/>
      <node text="5 ngày" bounds="[132,468][280,504]" clickable="true"/>
    </node>
  </node>
</hierarchy>"""
    target = {
        "bounds": [132, 468, 280, 504],
        "tap_kind": "timestamp",
        "tap_label": "5 ngày",
    }
    ctx: dict = {
        "open_post_before_extract": True,
        "post_open_verify": True,
    }
    with patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline."
        "resolve_post_open_targets_from_xml",
        return_value=(target, []),
    ), patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline."
        "hierarchy_is_fb_post_detail_from_xml",
        side_effect=[False, True],
    ), patch("asyncio.sleep") as sleep_mock:
        detail_xml, diag = await _maybe_open_fb_post_detail(
            exec_, "dev1", ctx, feed_xml
        )

    assert detail_xml == _SAMPLE_XML
    assert diag["reason_code"] == "ok"
    sleep_mock.assert_not_called()
    assert exec_.batches[0][0]["op"] == "click"
    assert exec_.batches[0][1] == {"op": "sleep", "seconds": 0.1}
    assert exec_.batches[0][2]["op"] == "dump_hierarchy"


@pytest.mark.asyncio
async def test_open_post_explicit_settle_is_not_clamped() -> None:
    exec_ = _SessionFakeExecutor()
    feed_xml = """<?xml version="1.0"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,200][1080,2200]">
    <node bounds="[0,400][1080,1100]">
      <node text="Author" bounds="[132,420][420,464]"/>
      <node text="5 ngày" bounds="[132,468][280,504]" clickable="true"/>
    </node>
  </node>
</hierarchy>"""
    target = {
        "bounds": [132, 468, 280, 504],
        "tap_kind": "timestamp",
        "tap_label": "5 ngày",
    }
    ctx: dict = {
        "open_post_before_extract": True,
        "post_open_verify": True,
        "post_open_tap_settle_s": 0.9,
    }
    with patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline."
        "resolve_post_open_targets_from_xml",
        return_value=(target, []),
    ), patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline."
        "hierarchy_is_fb_post_detail_from_xml",
        side_effect=[False, True],
    ):
        detail_xml, diag = await _maybe_open_fb_post_detail(
            exec_, "dev1", ctx, feed_xml
        )

    assert detail_xml == _SAMPLE_XML
    assert diag["reason_code"] == "ok"
    assert exec_.batches[0][1] == {"op": "sleep", "seconds": 0.9}


@pytest.mark.asyncio
async def test_open_post_prioritizes_narrow_author_gap_over_slow_header_fallbacks() -> None:
    exec_ = _SessionFakeExecutor()
    feed_xml = """<?xml version="1.0"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,200][1080,2200]">
    <node bounds="[0,400][1080,1100]">
      <node text="Author" bounds="[132,420][420,464]"/>
      <node text="5 ngày" bounds="[132,468][520,504]" clickable="true"/>
    </node>
  </node>
</hierarchy>"""
    target = {
        "bounds": [132, 468, 520, 504],
        "tap_kind": "timestamp",
        "tap_label": "5 ngày",
        "tap_alternates": [
            {
                "bounds": [420, 420, 980, 464],
                "tap_kind": "author_row_gap",
                "tap_label": "",
            },
            {
                "bounds": [600, 420, 780, 464],
                "tap_kind": "author_row_gap",
                "tap_label": "",
            },
        ],
    }
    ctx: dict = {
        "open_post_before_extract": True,
        "post_open_verify": True,
        "post_open_max_attempts": 2,
        "post_open_tap_settle_s": 0.1,
    }
    with patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline."
        "resolve_post_open_targets_from_xml",
        return_value=(target, []),
    ), patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline."
        "hierarchy_is_fb_post_detail_from_xml",
        side_effect=[False, True],
    ):
        detail_xml, diag = await _maybe_open_fb_post_detail(
            exec_, "dev1", ctx, feed_xml
        )

    assert detail_xml == _SAMPLE_XML
    assert diag["reason_code"] == "ok"
    assert diag["tap_kind"] == "author_row_gap"
    assert len(diag["attempts"]) == 1
    assert exec_.clicks[0] == (636, 442)


@pytest.mark.asyncio
async def test_open_post_keeps_primary_timestamp_as_second_attempt() -> None:
    exec_ = _SessionFakeExecutor()
    feed_xml = """<?xml version="1.0"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,200][1080,2200]">
    <node bounds="[0,400][1080,1100]">
      <node text="Author" bounds="[132,420][420,464]"/>
      <node text="5 ngày" bounds="[132,468][520,504]" clickable="true"/>
    </node>
  </node>
</hierarchy>"""
    target = {
        "bounds": [132, 468, 520, 504],
        "tap_kind": "timestamp",
        "tap_label": "5 ngày",
        "tap_alternates": [
            {
                "bounds": [420, 420, 980, 464],
                "tap_kind": "author_row_gap",
            },
            {
                "bounds": [600, 420, 780, 464],
                "tap_kind": "author_row_gap",
            },
        ],
    }
    ctx: dict = {
        "open_post_before_extract": True,
        "post_open_verify": True,
        "post_open_max_attempts": 2,
        "post_open_tap_settle_s": 0.1,
    }
    with patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline."
        "resolve_post_open_targets_from_xml",
        return_value=(target, []),
    ), patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline."
        "hierarchy_is_fb_post_detail_from_xml",
        side_effect=[False, False, True],
    ):
        detail_xml, diag = await _maybe_open_fb_post_detail(
            exec_, "dev1", ctx, feed_xml
        )

    assert detail_xml == _SAMPLE_XML
    assert diag["reason_code"] == "ok"
    assert [attempt["tap_kind"] for attempt in diag["attempts"]] == [
        "author_row_gap",
        "timestamp",
    ]


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
async def test_open_post_prefers_comment_sheet_when_detail_classifiers_overlap() -> None:
    exec_ = _SessionFakeExecutor()
    feed_xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1260,2800]">
  <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,300][1260,2600]">
    <node bounds="[0,420][1260,1200]">
      <node text="Trí Hưng" bounds="[132,440][420,500]"/>
      <node text="23 giờ" bounds="[132,510][300,560]" clickable="true"/>
      <node content-desc="Đây là cách GG làm trong cuộc đua AI =))"
            bounds="[36,600][1224,760]" clickable="true"/>
    </node>
  </node>
</hierarchy>"""
    detail_with_comments_xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1260,2800]">
  <node package="com.facebook.katana" class="android.widget.Button"
        clickable="true" content-desc="Đóng" bounds="[0,80][120,180]"/>
  <node package="com.facebook.katana" content-desc="Bài viết của Trí Hưng"
        bounds="[120,80][900,180]"/>
  <node package="com.facebook.katana"
        class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,300][1260,2500]">
    <node text="Tất cả bình luận" bounds="[40,1700][500,1780]"/>
    <node text="Người bình luận" bounds="[40,1820][400,1880]"/>
    <node text="Nội dung bình luận" bounds="[40,1900][1100,1980]"/>
  </node>
  <node package="com.facebook.katana"
        class="android.widget.AutoCompleteTextView"
        text="Viết bình luận…" bounds="[120,2500][1100,2640]"/>
</hierarchy>"""
    exec_._dump_xml = detail_with_comments_xml
    target = {
        "bounds": [132, 510, 300, 560],
        "tap_kind": "timestamp",
        "tap_label": "23 giờ",
        "post": {
            "_pid": "tri-hung-post",
            "post_key": "tri-hung-post-key",
            "stable_post_id": "tri-hung-stable",
            "author": "Trí Hưng",
            "timestamp": "23 giờ",
            "text": "Đây là cách GG làm trong cuộc đua AI =))",
        },
    }
    ctx: dict = {"open_post_before_extract": True, "post_open_verify": True}

    with patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline."
        "resolve_post_open_targets_from_xml",
        return_value=(target, []),
    ):
        detail_xml, diag = await _maybe_open_fb_post_detail(
            exec_, "dev1", ctx, feed_xml
        )

    assert detail_xml == detail_with_comments_xml
    assert diag["reason_code"] == "comment_sheet"
    assert diag["post_detail_verified"] is True
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
        ctx["open_post_detail"] = True
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
    assert snapshots == [feed_xml, comment_sheet_xml]
    assert ctx["expand_see_more_skipped"] == "comment_sheet"


@pytest.mark.asyncio
async def test_collect_fb_posts_keeps_feed_snapshot_when_opening_detail() -> None:
    feed_xml = """<?xml version="1.0"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.RecyclerView">
    <node text="feed-post-1" />
    <node text="feed-post-2" />
  </node>
</hierarchy>"""
    detail_xml = """<?xml version="1.0"?>
<hierarchy>
  <node text="opened-detail-post" />
</hierarchy>"""
    exec_ = _FakeExecutor(xml=feed_xml)
    exec_._dump_xml = feed_xml
    ctx: dict = {"open_post_before_extract": True, "expand_see_more": False}

    async def _opened_detail(*args, **kwargs):
        ctx["open_post_detail"] = True
        return detail_xml, {"reason_code": "ok"}

    with patch(
        "relay.extra_data.collector._maybe_open_fb_post_detail",
        new=_opened_detail,
    ):
        snapshots, err = await collect_xml_snapshots(exec_, "dev1", "fb_posts", ctx)

    assert err is None
    assert snapshots == [feed_xml, detail_xml]


@pytest.mark.asyncio
async def test_collect_comments_requires_verified_comment_sheet() -> None:
    exec_ = _FakeExecutor(
        xml='<hierarchy><node text="old post detail"/></hierarchy>'
    )
    ctx: dict = {
        "require_verified_parent": True,
        "comment_scroll_passes": 0,
    }

    snapshots, err = await collect_xml_snapshots(exec_, "dev1", "fb_comments", ctx)

    assert snapshots == []
    assert err == "comment_sheet_not_open"


@pytest.mark.asyncio
async def test_open_post_already_on_detail_avoids_extra_post_parse() -> None:
    exec_ = _SessionFakeExecutor()
    detail_xml = '<hierarchy><node text="detail"/></hierarchy>'
    ctx: dict = {
        "open_post_before_extract": True,
        "open_post_reuse_current_detail": True,
    }

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
async def test_open_post_does_not_reuse_stale_detail_by_default() -> None:
    exec_ = _SessionFakeExecutor()
    detail_xml = '<hierarchy><node text="old-detail"/></hierarchy>'
    ctx: dict = {"open_post_before_extract": True}

    with patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline.hierarchy_is_fb_post_detail_from_xml",
        return_value=True,
    ):
        opened_xml, diag = await _maybe_open_fb_post_detail(
            exec_, "dev1", ctx, detail_xml
        )

    assert opened_xml is None
    assert diag["reason_code"] == "stale_post_detail_requires_feed"
    assert exec_.press_back_calls == 1
    assert ctx.get("open_post_detail") is not True


@pytest.mark.asyncio
@pytest.mark.parametrize("group_locked", [True, False])
async def test_open_post_recovers_verified_stale_detail_while_group_back_is_locked(
    group_locked: bool,
) -> None:
    exec_ = _SessionFakeExecutor()
    stale_detail_xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1260,2800]">
  <node package="com.facebook.katana" class="android.widget.Button"
        clickable="true" content-desc="Đóng" bounds="[0,80][120,180]"/>
  <node package="com.facebook.katana" content-desc="Bài viết của Trí Hưng"
        bounds="[120,80][900,180]"/>
  <node package="com.facebook.katana"
        class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,300][1260,2500]">
    <node text="Tất cả bình luận" bounds="[40,1700][500,1780]"/>
  </node>
</hierarchy>"""
    fresh_feed_xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1260,2800]">
  <node text="Bạn viết gì đi…" bounds="[40,200][900,280]"/>
  <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true"
        bounds="[0,300][1260,2600]">
    <node bounds="[0,420][1260,1200]">
      <node text="Tác giả mới" bounds="[132,440][420,500]"/>
      <node text="1 giờ" bounds="[132,510][300,560]" clickable="true"/>
      <node content-desc="Bài viết mới" bounds="[36,600][1224,760]" clickable="true"/>
      <node content-desc="Bình luận" bounds="[300,900][700,980]" clickable="true"/>
    </node>
  </node>
</hierarchy>"""
    wrong_facebook_surface_xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1260,2800]">
  <node package="com.facebook.katana" text="Facebook" bounds="[40,120][500,220]"/>
  <node package="com.facebook.katana" text="Trang chủ" bounds="[40,260][500,340]"/>
</hierarchy>"""
    new_detail_xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1260,2800]">
  <node package="com.facebook.katana" class="android.widget.Button"
        clickable="true" content-desc="Đóng" bounds="[0,80][120,180]"/>
  <node package="com.facebook.katana" content-desc="Bài viết của Tác giả mới"
        bounds="[120,80][900,180]"/>
</hierarchy>"""
    target = {
        "bounds": [132, 510, 300, 560],
        "tap_kind": "timestamp",
        "tap_label": "1 giờ",
        "post": {
            "_pid": "new-post",
            "post_key": "new-post-key",
            "author": "Tác giả mới",
            "timestamp": "1 giờ",
            "text": "Bài viết mới",
        },
    }
    ctx: dict = {
        "open_post_before_extract": True,
        "post_open_verify": True,
        "strategy": "fb_posts",
        "post_open_stale_back_settle_s": 0,
        "post_open_stale_feed_verify_retries": 2,
        "post_open_stale_feed_verify_pause_s": 0,
    }
    if group_locked:
        ctx["tags"] = "group,crawl"

    with patch(
        "relay.extra_data.collector._press_back",
        return_value=True,
    ) as back_mock, patch(
        "relay.extra_data.collector._dump_hierarchy",
        side_effect=[
            stale_detail_xml,
            wrong_facebook_surface_xml,
            fresh_feed_xml,
        ],
    ) as dump_mock, patch(
        "relay.extra_data.parsers.facebook.post_open_pipeline."
        "resolve_post_open_targets_from_xml",
        return_value=(target, []),
    ), patch(
        "relay.extra_data.collector._u2_click_post_open_target_and_dump",
        return_value=(True, "click_coord_batch_dump", new_detail_xml),
    ):
        opened_xml, diag = await _maybe_open_fb_post_detail(
            exec_, "dev1", ctx, stale_detail_xml
        )

    assert opened_xml == new_detail_xml
    assert diag["reason_code"] == "ok"
    assert ctx["post_open_feed_refreshed"] is True
    back_mock.assert_awaited_once()
    assert dump_mock.await_count == 3


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


@pytest.mark.asyncio
async def test_collect_xml_snapshots_attaches_preparsed_fb_comments(monkeypatch) -> None:
    import relay.extra_data.parsers.facebook as facebook

    def fake_parse(xml, parent_post_id=None, max_items=400):
        return [{"comment_key": "c1", "text": "first"}], {"reason_code": "ok"}

    monkeypatch.setattr(facebook, "parse_fb_comments_from_xml_with_diagnostic", fake_parse)

    context = {
        "collection": "c1",
        "comment_scroll_passes": 0,
        "comment_respect_post_count": False,
        "preparse_fb_comments": True,
    }
    snapshots, err = await collect_xml_snapshots(
        _FakeExecutor(xml=_SAMPLE_XML),
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert snapshots == [_SAMPLE_XML]
    assert context["agent_boot_preparsed_comments"] is True
    payload = build_ingest_payload(
        serial="dev1",
        strategy="fb_comments",
        context=context,
        snapshots=snapshots,
    )
    assert payload["preparsed"]["items"] == [{"comment_key": "c1", "text": "first"}]
    assert payload["preparsed"]["snapshot_hashes"] == [
        hashlib.sha256(_SAMPLE_XML.encode("utf-8")).hexdigest()
    ]
    assert "xml_snapshots" not in payload


@pytest.mark.asyncio
async def test_collect_xml_snapshots_preparsed_comments_merge_multiple_frames(monkeypatch) -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    import relay.extra_data.parsers.facebook as facebook

    def fake_parse(xml, parent_post_id=None, max_items=400):
        if "frame-2" in xml:
            return [
                {"comment_key": "c1", "text": "duplicate"},
                {"comment_key": "c2", "text": "second"},
            ], {"reason_code": "ok"}
        return [{"comment_key": "c1", "text": "first"}], {"reason_code": "ok"}

    monkeypatch.setattr(facebook, "parse_fb_comments_from_xml_with_diagnostic", fake_parse)

    def _frame_xml(idx: int) -> str:
        return _sheet_xml().replace(
            "</hierarchy>",
            f'<node text="frame-{idx}" /></hierarchy>',
        )

    class _TwoFrameExecutor(_FakeExecutor):
        def __init__(self) -> None:
            super().__init__(xml=_frame_xml(1))
            self._n = 0

        async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
            if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
                self._n += 1
                self._dump_xml = _frame_xml(min(self._n, 2))
            return await super().run_batch(serial, actions, early_exit=early_exit)

    context = {
        "collection": "c1",
        "comment_scroll_passes": 1,
        "comment_respect_post_count": False,
        "comment_stop_if_no_new": False,
        "stop_if_no_new": False,
        "comment_no_growth_break": 0,
        "preparse_fb_comments": True,
    }
    snapshots, err = await collect_xml_snapshots(
        _TwoFrameExecutor(),
        "dev1",
        "fb_comments",
        context,
    )

    assert err is None
    assert len(snapshots) == 2
    payload = build_ingest_payload(
        serial="dev1",
        strategy="fb_comments",
        context=context,
        snapshots=snapshots,
    )
    assert [item["comment_key"] for item in payload["preparsed"]["items"]] == ["c1", "c2"]
    assert payload["preparsed"]["snapshot_count"] == 2
    assert payload["preparsed"]["snapshot_hashes"] == [
        hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
        for snapshot in snapshots
    ]
    assert "xml_snapshots" not in payload


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


def test_build_ingest_payload_uses_preparsed_comments_without_raw_snapshots() -> None:
    context = {
        "collection": "c1",
        "agent_boot_preparsed_comments": True,
        "_preparsed_fb_comment_items": [{"comment_key": "c1", "text": "first"}],
        "_preparsed_fb_comment_diagnostic": {"reason_code": "ok", "comments_returned": 1},
        "_preparsed_fb_comment_snapshot_count": 2,
        "_preparsed_fb_comment_xml_bytes": 1234,
    }

    payload = build_ingest_payload(
        serial="dev1",
        strategy="fb_comments",
        context=context,
        snapshots=[_SAMPLE_XML, _SAMPLE_XML + " "],
        request_id="extra-abc",
    )

    assert payload["preparsed"]["items"] == [{"comment_key": "c1", "text": "first"}]
    assert payload["preparsed"]["snapshot_count"] == 2
    assert payload["preparsed"]["xml_bytes"] == 1234
    assert payload["preparsed"]["snapshot_hashes"] == [
        hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
        for snapshot in [_SAMPLE_XML, _SAMPLE_XML + " "]
    ]
    assert "xml_snapshots" not in payload
    assert "_preparsed_fb_comment_items" not in payload["context"]
    assert context["_preparsed_fb_comment_items"] == [{"comment_key": "c1", "text": "first"}]


def test_build_ingest_payload_can_keep_debug_snapshots_with_preparsed_comments() -> None:
    payload = build_ingest_payload(
        serial="dev1",
        strategy="fb_comments",
        context={
            "collection": "c1",
            "debug_xml_snapshots": True,
            "agent_boot_preparsed_comments": True,
            "_preparsed_fb_comment_items": [{"comment_key": "c1", "text": "first"}],
        },
        snapshots=[_SAMPLE_XML, _SAMPLE_XML + " "],
    )

    assert "preparsed" in payload
    assert "xml_snapshots" in payload
