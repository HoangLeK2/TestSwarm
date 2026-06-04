"""Unit tests for post→comment child query link filters."""
from __future__ import annotations

from types import SimpleNamespace

from services.content.parent_links import parent_link_candidates, parent_post_id_values


def test_parent_post_id_values_includes_parser_pid_keys() -> None:
    item = SimpleNamespace(
        raw_data={
            "post_key": "pk-long",
            "_pid": "pid-short",
            "stable_post_id": "stable-1",
            "fb_post_id": "fb-1",
        },
        content_hash="hash",
        execution_id="exec-1",
        body=None,
        title=None,
        author=None,
    )
    values = parent_post_id_values(item)
    assert "pk-long" in values
    assert "pid-short" in values
    assert "stable-1" in values
    assert "fb-1" in values


def test_parent_link_candidates_include_scoped_hash_for_children_raw_match() -> None:
    item = SimpleNamespace(
        content_hash="scoped-hash-value",
        execution_id="exec-1",
        raw_data={"post_key": "pk-1", "_pid": "pid-1"},
        body="text",
        title=None,
        author=None,
    )
    candidates = parent_link_candidates(item)
    assert "scoped-hash-value" in candidates
    assert "pid-1" in candidates
