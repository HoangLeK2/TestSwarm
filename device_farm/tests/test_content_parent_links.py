from __future__ import annotations

from types import SimpleNamespace

from services.content.parent_links import parent_link_candidates, parent_post_id_values
from services.content_store import compute_content_hash, scope_content_hash


def test_parent_link_candidates_includes_hash_variants() -> None:
    payload = {"post_key": "pk-1", "text": "hello post", "author": "Alice"}
    scope = "exec-abc"
    base = compute_content_hash(payload, "post_key")
    scoped = scope_content_hash(base, scope)
    item = SimpleNamespace(
        content_hash=scoped,
        execution_id=scope,
        raw_data=payload,
        body="hello post",
        title=None,
        author="Alice",
    )
    candidates = parent_link_candidates(item)
    assert scoped in candidates
    assert base in candidates
    assert "pk-1" in candidates


def test_parent_post_id_values_reads_parser_ids() -> None:
    item = SimpleNamespace(
        raw_data={"post_key": "pk-99", "parent_post_id": "pid-99"},
        content_hash="x",
        execution_id=None,
        body=None,
        title=None,
        author=None,
    )
    assert parent_post_id_values(item) == ["pk-99", "pid-99"]
