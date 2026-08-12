from __future__ import annotations

import pytest

from services.extraction_usecase import persist_data_items, resolve_comment_parent_hash
from services import extraction_usecase as extraction_usecase_mod


@pytest.mark.asyncio
async def test_persist_data_items_empty_input_is_noop() -> None:
    report, offsets = await persist_data_items(
        data=[],
        data_var="posts",
        offsets={},
        collection="test",
    )
    assert report.saved_count == 0
    assert report.duplicate_count == 0
    assert report.error_count == 0
    assert offsets == {}


@pytest.mark.asyncio
async def test_persist_data_items_scalar_does_not_write_offsets() -> None:
    report, offsets = await persist_data_items(
        data={"text": "single"},
        data_var="one_post",
        offsets={"one_post": 99},
        collection="test",
        # Force error path (no DB write), we only assert offset behavior.
        dedupe_field=None,
    )
    assert report.error_count >= 0
    assert offsets["one_post"] == 99


@pytest.mark.asyncio
async def test_persist_data_items_malformed_list_marks_error() -> None:
    report, offsets = await persist_data_items(
        data=["a", "b"],
        data_var="bad_list",
        offsets={},
        collection="test",
    )
    assert report.error_count == 1
    assert offsets == {}


def test_resolve_comment_parent_hash_prefers_pid_map() -> None:
    ctx = {
        "_post_id_map": {"pid1": "hash_from_pid"},
        "_active_comment_parent_hash": "explicit_tap_hash",
        "_first_new_post_hash": "stale_legacy_hash",
    }
    # Direct pid map hit — always preferred.
    assert resolve_comment_parent_hash(ctx, "pid1") == "hash_from_pid"
    # Miss on pid map → fall back to explicit hash set by tap_fb_comment_button.
    assert resolve_comment_parent_hash(ctx, "pid2") == "explicit_tap_hash"


def test_resolve_comment_parent_hash_returns_none_without_explicit_tap() -> None:
    """Old behavior silently fell back to _first_new_post_hash (top-of-feed at
    last extract, NOT the actually-tapped post) when pid was missing from the
    map — this was the root cause of comments being attached to the wrong
    post. New behavior returns None so the caller can treat parent as unknown
    instead of guessing.
    """
    ctx = {
        "_post_id_map": {"pid1": "hash_from_pid"},
        # _first_new_post_hash is NOT a valid fallback anymore.
        "_first_new_post_hash": "stale_legacy_hash",
    }
    assert resolve_comment_parent_hash(ctx, "pid_missing") is None
    assert resolve_comment_parent_hash(ctx, None) is None


@pytest.mark.asyncio
async def test_persist_data_items_stops_on_first_error_and_updates_offset(monkeypatch) -> None:
    calls = {"n": 0, "account_ids": []}

    async def _fake_save_content_item(**kwargs):
        calls["n"] += 1
        calls["account_ids"].append(kwargs.get("account_id"))
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return {"saved": True, "id": f"id-{calls['n']}"}

    monkeypatch.setattr(extraction_usecase_mod, "save_content_item", _fake_save_content_item)

    report, offsets = await persist_data_items(
        data=[{"text": "a"}, {"text": "b"}, {"text": "c"}],
        data_var="posts",
        offsets={"posts": 0},
        collection="x",
        account_id="account-persist",
    )
    assert report.saved_count == 1
    assert report.error_count == 1
    assert calls["n"] == 2
    assert calls["account_ids"] == ["account-persist", "account-persist"]
    # Only first successful item is committed in offset progression.
    assert offsets["posts"] == 1
