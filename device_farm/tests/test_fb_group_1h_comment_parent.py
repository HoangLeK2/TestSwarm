"""fb_group_1h + fb_posts/fb_comments: comments must use the top feed post _pid.

Executor sets ctx["_fb_comment_parent_pid"] after each fb_posts extract; template
passes parent_post_id_var so parse_fb_comments_from_xml does not rely on
_compute_post_id_from_nodes (often None on VN comment sheets).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Generator, List

import pytest

from db.seeds.scenario_templates import BUILTIN_TEMPLATES
from services.content_store import compute_content_hash
from tasks.fb_extract import parse_fb_comments_from_xml, parse_fb_posts_from_xml

CAPTURES = Path(__file__).resolve().parent.parent / "captures"


def _require_capture_file(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"missing capture fixture: {path.name}")


def _walk_steps(steps: List[Dict[str, Any]] | None) -> Generator[Dict[str, Any], None, None]:
    for s in steps or []:
        yield s
        if s.get("type") == "loop":
            yield from _walk_steps(s.get("steps"))
        for key in ("then", "else"):
            yield from _walk_steps(s.get(key))


def test_fb_group_1h_template_fb_comments_has_parent_post_id_var() -> None:
    spec = next(t for t in BUILTIN_TEMPLATES if t["name"] == "fb_group_1h")
    fb_comment = [
        s
        for s in _walk_steps(spec.get("steps"))
        if s.get("type") == "extract" and s.get("strategy") == "fb_comments"
    ]
    assert fb_comment, "fb_group_1h must include extract fb_comments"
    for step in fb_comment:
        assert step.get("parent_post_id_var") == "_fb_comment_parent_pid", step
        assert step.get("extract_profile"), step
        assert step.get("strategy_version"), step


def test_fb_group_1h_template_extract_posts_has_profile_and_version() -> None:
    spec = next(t for t in BUILTIN_TEMPLATES if t["name"] == "fb_group_1h")
    fb_posts = [
        s
        for s in _walk_steps(spec.get("steps"))
        if s.get("type") == "extract" and s.get("strategy") == "fb_posts"
    ]
    assert fb_posts, "fb_group_1h must include extract fb_posts"
    for step in fb_posts:
        assert step.get("extract_profile"), step
        assert step.get("strategy_version"), step


def test_fb_group_1h_save_comments_uses_active_parent_hash() -> None:
    spec = next(t for t in BUILTIN_TEMPLATES if t["name"] == "fb_group_1h")
    extracts = [
        s
        for s in _walk_steps(spec.get("steps"))
        if s.get("type") == "extract"
        and s.get("strategy") == "fb_comments"
        and s.get("collection")
    ]
    assert extracts, "expected extract fb_comments with inline save (collection)"
    for s in extracts:
        assert s.get("save_parent_id_var") == "_active_comment_parent_hash", s


def test_171940_comment_rows_match_feed_top_post_pid() -> None:
    """Golden: same session feed pre-dump + comment scroll — all bodies share parent_post_id."""
    root = CAPTURES / "49c62ff79ec0c35d_2026-04-12_171940"
    _require_capture_file(root / "step_000_extract_pre_hierarchy.xml")
    _require_capture_file(root / "step_002_scroll_down_hierarchy.xml")
    feed_xml = (root / "step_000_extract_pre_hierarchy.xml").read_text(encoding="utf-8", errors="replace")
    com_xml = (root / "step_002_scroll_down_hierarchy.xml").read_text(encoding="utf-8", errors="replace")
    posts = parse_fb_posts_from_xml(feed_xml)
    assert posts
    pid = posts[0]["_pid"]
    assert pid
    rows = parse_fb_comments_from_xml(com_xml, parent_post_id=pid, max_items=200)
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    assert len(bodies) >= 5
    for r in bodies:
        assert r.get("parent_post_id") == pid


def test_feed_comment_preview_uses_matching_row_not_last_binh_luan() -> None:
    """Three feed rows: parent_post_id=posts[0]._pid must read preview under row 1, not row 3."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true"
        bounds="[0,200][1080,2200]">
    <node bounds="[0,300][1080,880]">
      <node class="android.widget.TextView" text="AuthorA" bounds="[40,320][200,360]"/>
      <node class="android.widget.TextView"
            text="First post body here xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            bounds="[40,400][1000,500]"/>
      <node class="android.widget.TextView" text="1 giờ" bounds="[40,520][140,560]"/>
      <node class="android.widget.Button" text="Bình luận" bounds="[400,700][600,780]"/>
      <node class="android.widget.TextView" text="FanOne" bounds="[200,800][340,830]"/>
      <node class="android.widget.TextView" text="Nice one" bounds="[200,835][400,865]"/>
    </node>
    <node bounds="[0,880][1080,1380]">
      <node class="android.widget.TextView" text="AuthorB" bounds="[40,900][200,940]"/>
      <node class="android.widget.TextView"
            text="Second post body yyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
            bounds="[40,980][1000,1080]"/>
      <node class="android.widget.TextView" text="2 giờ" bounds="[40,1100][140,1140]"/>
      <node class="android.widget.Button" text="Bình luận" bounds="[400,1200][600,1280]"/>
    </node>
    <node bounds="[0,1380][1080,1900]">
      <node class="android.widget.TextView" text="AuthorC" bounds="[40,1400][200,1440]"/>
      <node class="android.widget.TextView"
            text="Third post body zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"
            bounds="[40,1480][1000,1580]"/>
      <node class="android.widget.Button" text="Bình luận" bounds="[400,1700][600,1780]"/>
      <node class="android.widget.TextView" text="Spammer" bounds="[200,1800][360,1830]"/>
      <node class="android.widget.TextView" text="Spam bottom" bounds="[200,1835][500,1865]"/>
    </node>
  </node>
</hierarchy>"""
    posts = parse_fb_posts_from_xml(xml)
    assert len(posts) >= 3, posts
    pid_top = posts[0]["_pid"]
    rows = parse_fb_comments_from_xml(xml, parent_post_id=pid_top, max_items=20)
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    joined = " ".join((r.get("text") or "") for r in bodies)
    assert "Nice one" in joined
    assert "Spam bottom" not in joined
    for r in bodies:
        assert r.get("parent_post_id") == pid_top


def test_001701_capture_parses_ha_thang_middle_card_not_junk() -> None:
    """Katana: no combined stats line → a11y Thích/Bình luận must not merge into body (junk filter)."""
    cap = (
        CAPTURES / "49c62ff79ec0c35d_2026-04-13_001701" / "step_000_extract_hierarchy.xml"
    )
    if not cap.is_file():
        pytest.skip("capture 001701 not in tree")
    posts = parse_fb_posts_from_xml(cap.read_text(encoding="utf-8", errors="replace"), 0)
    assert len(posts) >= 3, posts
    authors = [p.get("author") for p in posts]
    assert "Hà Thắng" in authors
    ha = next(p for p in posts if p.get("author") == "Hà Thắng")
    assert "Nút Thích" not in (ha.get("text") or "")
    assert "nhấn đúp" not in (ha.get("text") or "").lower()
    assert ha.get("comment_preview")
    assert "Mac mini" in (ha.get("comment_preview") or "")


def test_002858_comment_sheet_first_row_op_image_comment() -> None:
    """Full thread: OP name on avatar (x<150) + badge ``Tác giả`` + image-only a11y ``Ảnh``."""
    cap = CAPTURES / "49c62ff79ec0c35d_2026-04-13_002858" / "step_000_extract_hierarchy.xml"
    if not cap.is_file():
        pytest.skip("capture 002858 not in tree")
    rows = parse_fb_comments_from_xml(cap.read_text(encoding="utf-8", errors="replace"), max_items=20)
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    assert len(bodies) >= 1
    first = bodies[0]
    assert "minh" in (first.get("author") or "").lower()
    assert "thành" in (first.get("author") or "").lower()
    badges = first.get("badges") or []
    assert any("tác giả" in (b or "").lower() for b in badges)
    assert "[image]" in (first.get("text") or "")
    assert first.get("timestamp") == "1 ngày"
    assert first.get("likes") == "2"
    assert first.get("reactions") == "2"
    assert first.get("post_reactions") == "167"
    assert first.get("post_shares") == "20"


def test_recycler_items_sorted_by_top_y_when_dom_order_is_reversed() -> None:
    """StaggeredGrid: XML children may be bottom-first; posts[0] must be visually top card."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true"
        bounds="[0,200][1080,2200]">
    <node bounds="[0,900][1080,1500]">
      <node class="android.widget.TextView" text="LowerAuthor" bounds="[40,920][260,960]"/>
      <node class="android.widget.TextView"
            text="Lower post body yyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
            bounds="[40,1000][1000,1100]"/>
      <node class="android.widget.TextView" text="5 giờ" bounds="[40,1120][140,1160]"/>
    </node>
    <node bounds="[0,280][1080,820]">
      <node class="android.widget.TextView" text="UpperAuthor" bounds="[40,300][260,340]"/>
      <node class="android.widget.TextView"
            text="Upper post body xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            bounds="[40,380][1000,480]"/>
      <node class="android.widget.TextView" text="1 giờ" bounds="[40,500][140,540]"/>
    </node>
  </node>
</hierarchy>"""
    posts = parse_fb_posts_from_xml(xml)
    assert len(posts) >= 2, posts
    assert posts[0].get("author") == "UpperAuthor"
    assert "Upper post body" in (posts[0].get("text") or "")
    assert any("Lower post body" in (p.get("text") or "") for p in posts[1:])


def test_post_id_map_resolves_same_hash_as_compute_content_hash() -> None:
    path = CAPTURES / "49c62ff79ec0c35d_2026-04-12_171940/step_000_extract_pre_hierarchy.xml"
    _require_capture_file(path)
    feed_xml = path.read_text(encoding="utf-8", errors="replace")
    posts = parse_fb_posts_from_xml(feed_xml)
    pid = posts[0]["_pid"]
    expected = compute_content_hash(posts[0], dedupe_field="post_key")
    ctx: Dict[str, Any] = {"_post_id_map": {pid: expected}}
    parent_hash = ctx.get("_post_id_map", {}).get(pid) or ctx.get("_first_new_post_hash")
    assert parent_hash == expected
