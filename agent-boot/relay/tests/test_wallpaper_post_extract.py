"""Regression: wallpaper / gradient posts must not store chrome as post text."""

from __future__ import annotations

from relay.extra_data.parsers.facebook.parser import _collect_text_nodes, _parse_xml
from relay.extra_data.parsers.facebook.post_extractor import (
    _clean_extracted_post_body,
    _extract_post,
    _is_wallpaper_meta_only,
    _strip_wallpaper_chrome,
)


def test_strip_wallpaper_chrome_removes_meta_prefix() -> None:
    assert _strip_wallpaper_chrome("Hình nền GPT Go dùng codex ổn ko các bác") == (
        "GPT Go dùng codex ổn ko các bác"
    )
    assert _strip_wallpaper_chrome("Hình minh họa tím nhạt, hình nền") == ""
    assert _strip_wallpaper_chrome(
        "Nguyễn Sơn Hình minh họa tím nhạt, hình nền", author="Nguyễn Sơn"
    ) == ""


def test_wallpaper_meta_only_detects_background_labels() -> None:
    assert _is_wallpaper_meta_only("hình nền")
    assert _is_wallpaper_meta_only("Hình minh họa tím nhạt, hình nền")
    assert not _is_wallpaper_meta_only("Có cách nào để quay về GPT 5.3 Codex không các bác")


def test_extract_wallpaper_gradient_post_keeps_real_copy() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.view.ViewGroup" bounds="[0,900][1260,2200]">
    <node class="android.widget.Button" text="Nguyễn Sơn" clickable="true" bounds="[210,920][620,980]"/>
    <node class="android.view.ViewGroup" text="1 ngày•Chia sẻ với: Nhóm công khai" bounds="[210,990][900,1040]"/>
    <node class="android.view.ViewGroup" content-desc="Hình minh họa tím nhạt, hình nền" bounds="[42,1050][1218,1700]"/>
    <node class="android.view.ViewGroup"
      text="Có cách nào để quay về GPT 5.3 Codex không các bác. 5.5 cực tốn token"
      content-desc="Có cách nào để quay về GPT 5.3 Codex không các bác. 5.5 cực tốn token"
      clickable="true" bounds="[105,1200][1155,1420]"/>
    <node class="android.widget.Button" content-desc="Bình luận" clickable="true" bounds="[154,1700][308,1850]"/>
  </node>
</hierarchy>"""
    root = _parse_xml(xml)
    nodes = _collect_text_nodes(root, toolbar_cutoff_y=0)
    post = _extract_post(nodes, 0)
    assert post is not None
    assert post["author"] == "Nguyễn Sơn"
    assert "gpt 5.3 codex" in post["text"].casefold()
    assert "hình minh họa" not in post["text"].casefold()
    assert "hình nền" not in post["text"].casefold()
    assert "nguyễn sơn" not in post["text"].casefold()


def test_extract_merged_wallpaper_a11y_node_does_not_pollute_body() -> None:
    """FB sometimes merges author + wallpaper meta in one content-desc node."""
    cluster = [
        {"text": "Nguyễn Sơn", "bounds": (210, 920, 620, 980), "is_author_hint": False},
        {"text": "1 ngày•Chia sẻ với: Nhóm công khai", "bounds": (210, 990, 900, 1040), "is_author_hint": False},
        {
            "text": "Nguyễn Sơn Hình minh họa tím nhạt, hình nền",
            "bounds": (42, 1050, 1218, 1700),
            "is_author_hint": False,
        },
    ]
    post = _extract_post(cluster, 0)
    assert post is not None
    assert post["author"] == "Nguyễn Sơn"
    assert post["text"] == ""
    assert _clean_extracted_post_body(
        "Nguyễn Sơn Hình minh họa tím nhạt, hình nền", author="Nguyễn Sơn"
    ) == ""
