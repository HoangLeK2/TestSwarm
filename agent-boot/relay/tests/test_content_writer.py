from __future__ import annotations

from datetime import datetime, timezone

from relay.extra_data.writer import (
    build_content_item_row,
    compute_content_hash,
    scope_content_hash,
)

# The agent no longer holds a database handle — persistence lives in
# device_farm/services/content/edge_ingest.py, covered by
# device_farm/tests/test_edge_ingest_parity.py. What must stay locked here is
# the hash contract: device_farm recomputes content_hash from the raw item and
# rejects anything it cannot derive, so these two sides have to agree exactly.


def test_hash_matches_content_store_contract() -> None:
    data = {"post_key": "abc", "text": "hello"}
    base = compute_content_hash(data, dedupe_field="post_key")

    assert compute_content_hash({"b": 2, "a": 1}) == compute_content_hash({"a": 1, "b": 2})
    assert scope_content_hash(base, "run-1") != base
    assert scope_content_hash(base, "run-1") == scope_content_hash(base, "run-1")


def test_build_content_item_row_maps_fields_and_scopes_hash() -> None:
    captured = datetime(2026, 5, 15, 4, 0, tzinfo=timezone.utc)
    raw = {
        "post_key": "p1",
        "text": "  hello  ",
        "author": " Alice ",
        "reactions": "1.2K",
        "comments": "3",
        "shares": "4",
        "views": "5K",
        "timestamp": "2 hours ago",
        "media_artifacts": ["https://example.test/a.jpg"],
    }
    row = build_content_item_row(
        raw,
        {
            "collection": "fb",
            "platform": "facebook",
            "content_type": "post",
            "device_serial": "serial-1",
            "campaign_id": "camp",
            "execution_id": "exec",
            "user_id": "user",
            "scenario_name": "scenario",
            "hash_scope": "scope",
            "dedupe_field": "post_key",
        },
        captured_at=captured,
    )

    assert row["collection"] == "fb"
    assert row["body"] == "hello"
    assert row["author"] == "Alice"
    assert row["likes_count"] == 1200
    assert row["comments_count"] == 3
    assert row["shares_count"] == 4
    assert row["views_count"] == 5000
    assert row["media_urls"] == ["https://example.test/a.jpg"]
    assert row["raw_data"] == raw
    assert row["content_date"] == datetime(2026, 5, 15, 2, 0, tzinfo=timezone.utc)
    assert row["content_hash"] == scope_content_hash(compute_content_hash(raw, "post_key"), "scope")


def test_build_content_item_row_parses_vietnamese_decimal_suffix_counts() -> None:
    row = build_content_item_row(
        {"post_key": "p1", "text": "hello", "reactions": "60,5K"},
        {"collection": "fb", "content_type": "post"},
    )

    assert row["likes_count"] == 60500


def test_parent_hash_is_scoped_for_comments() -> None:
    row = build_content_item_row(
        {"comment_key": "c1", "text": "comment"},
        {
            "collection": "fb",
            "content_type": "comment",
            "hash_scope": "scope",
            "dedupe_field": "comment_key",
        },
        parent_id="parent-base-hash",
        item_level=1,
    )

    assert row["item_level"] == 1
    assert row["parent_id"] == scope_content_hash("parent-base-hash", "scope")
