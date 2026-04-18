from __future__ import annotations

import pytest

from temporal.activities import DeviceActivities
from temporal.shared import SaveExtractionInput, ExtractInput


@pytest.mark.asyncio
async def test_temporal_save_extraction_contract_counts(monkeypatch) -> None:
    activities = DeviceActivities()
    monkeypatch.setattr("temporal.activities.activity.heartbeat", lambda *_args, **_kwargs: None)

    async def _fake_persist_data_items(**kwargs):
        class _Report:
            saved_count = 2
            duplicate_count = 1
            error_count = 0

        return _Report(), {"comments": 3}

    monkeypatch.setattr(
        "temporal.activities.persist_data_items",
        _fake_persist_data_items,
    )

    inp = SaveExtractionInput(
        device_serial="49c62ff79ec0c35d",
        step={
            "type": "save_extraction",
            "data_var": "comments",
            "collection": "fb_group_posts",
            "save_parent_id_var": "_active_comment_parent_hash",
        },
        context={
            "comments": [{"text": "a"}, {"text": "b"}, {"text": "c"}],
            "_active_comment_parent_hash": "parent_hash",
            "__save_extraction_offsets__": {"comments": 0},
        },
    )
    out = await activities.execute_save_extraction(inp)
    assert out.ok is True
    assert out.details["saved_count"] == 2
    assert out.details["duplicate_count"] == 1
    assert out.details["error_count"] == 0
    assert out.details["updated_offsets"]["comments"] == 3


@pytest.mark.asyncio
async def test_temporal_extract_profile_defaults_apply_to_fb_comments(monkeypatch) -> None:
    activities = DeviceActivities()
    monkeypatch.setattr("temporal.activities.activity.heartbeat", lambda *_args, **_kwargs: None)

    class _FakeDevice:
        def __init__(self) -> None:
            self.scroll_calls = 0

        def scroll(self, *_args, **_kwargs) -> None:
            self.scroll_calls += 1

        def hierarchy_xml(self, force_refresh: bool = False) -> str:
            return "<hierarchy/>"

    fake_device = _FakeDevice()
    monkeypatch.setattr("temporal.activities._get_device", lambda _serial: fake_device)

    def _fake_parse_fb_comments_from_xml(_xml, parent_post_id=None, max_items=50):
        # Assert profile default from balanced is applied through normalization.
        assert max_items == 400
        return [{"author": "a", "text": "x", "comment_key": "k1", "parent_post_id": parent_post_id}]

    monkeypatch.setattr(
        "tasks.fb_extract.parse_fb_comments_from_xml",
        _fake_parse_fb_comments_from_xml,
    )
    monkeypatch.setattr("tasks.fb_extract._dedup_comments", lambda rows: rows)
    monkeypatch.setattr("tasks.fb_extract._is_junk_parsed_comment_row", lambda _r: False)
    monkeypatch.setattr("tasks.fb_extract._post_id_from_ctx", lambda _ctx, _v: "pid-1")

    inp = ExtractInput(
        device_serial="49c62ff79ec0c35d",
        step={
            "type": "extract",
            "strategy": "fb_comments",
            "extract_profile": "balanced",
        },
        context={},
    )
    out = await activities.execute_extract(inp)
    assert out.ok is True
    assert out.details["comment_scan"]["max_items"] == 400


@pytest.mark.asyncio
async def test_temporal_extract_inline_save_uses_shared_offset_namespace(monkeypatch) -> None:
    activities = DeviceActivities()
    monkeypatch.setattr("temporal.activities.activity.heartbeat", lambda *_args, **_kwargs: None)

    class _FakeDevice:
        def hierarchy_xml(self, force_refresh: bool = False) -> str:
            return "<hierarchy/>"

    monkeypatch.setattr("temporal.activities._get_device", lambda _serial: _FakeDevice())
    monkeypatch.setattr("tasks.fb_extract.parse_fb_posts_from_xml", lambda _xml, source_index=0: [{"text": "p1"}])
    monkeypatch.setattr("tasks.fb_extract._dedup", lambda rows: rows)
    monkeypatch.setattr("tasks.fb_extract.is_fb_post_truncated", lambda _p: False)

    async def _fake_persist_data_items(**kwargs):
        class _Report:
            saved_count = 1
            duplicate_count = 0
            error_count = 0

        return _Report(), {"posts": 1}

    monkeypatch.setattr("temporal.activities.persist_data_items", _fake_persist_data_items)

    inp = ExtractInput(
        device_serial="49c62ff79ec0c35d",
        step={
            "type": "extract",
            "strategy": "fb_posts",
            "expand_see_more": False,
            "collection": "fb_group_posts",
            "dedupe_field": "post_key",
        },
        context={"posts": []},
    )
    out = await activities.execute_extract(inp)
    assert out.ok is True
    assert out.context["__save_extraction_offsets__"]["posts"] == 1
