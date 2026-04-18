from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent


def _walk_steps(steps: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for step in steps or []:
        out.append(step)
        if step.get("type") == "loop":
            out.extend(_walk_steps(step.get("steps")))
        for key in ("then", "else"):
            out.extend(_walk_steps(step.get(key)))
    return out


def _assert_comment_extract_dedupe_comment_key(steps: list[dict[str, Any]]) -> None:
    comment_extracts = [
        s for s in _walk_steps(steps)
        if s.get("type") == "extract" and s.get("strategy") == "fb_comments"
    ]
    assert comment_extracts, "expected at least one fb_comments extract step"
    for step in comment_extracts:
        assert step.get("dedupe_field") == "comment_key", step


def test_index_json_comment_extract_uses_comment_key_dedupe() -> None:
    data = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    _assert_comment_extract_dedupe_comment_key(data.get("steps", []))


def test_scenario_fb_group_crawl_comment_extract_uses_comment_key_dedupe() -> None:
    data = json.loads((ROOT / "scenarios" / "fb_group_crawl.json").read_text(encoding="utf-8"))
    _assert_comment_extract_dedupe_comment_key(data.get("steps", []))
