"""Corpus + contract ``fb_group_1h`` (``db/seeds/scenario_templates.py``).

Luồng chuẩn: template **fb_group_1h** gọi ``extract`` ``strategy=fb_posts`` / ``fb_comments``
→ context ``posts`` / ``comments`` là output của ``tasks.fb_extract`` (``parse_fb_posts_from_xml``,
``parse_fb_comments_from_xml`` + executor hydration). Khi ``collection`` được set trên ``extract``,
runtime tự gọi cùng luồng lưu như ``save_extraction`` (``services.content_store.save_content_item``)
với ``platform``, ``content_type``, ``dedupe_field`` như trong bước extract.

1. **Contract:** test đọc ``BUILTIN_TEMPLATES`` để không lệch với ``fb_group_1h`` (dedupe ``post_key`` /
   ``comment_key``, ``group_post``, v.v.).
2. **Độ khớp dump:** frame ``step_*_extract_hierarchy.xml`` — author / body / badge phải có trong XML.
3. **Lưu DB (SQLite):** gọi ``save_content_item`` với *cùng* tham số save như template (collection test
   có suffix để tách biệt). ``parent_id`` comment = ``content_hash`` của **post đầu** parse từ cùng file XML
   (giống hướng ``_active_comment_parent_hash`` trên feed một bài nổi; không phải đa-bài hoàn hảo).

Cần: ``aiosqlite`` (nhóm dev).

**Trace SQLite ra file:** đặt ``DEVICE_FARM_TRACE_SQLITE=1`` rồi chạy pytest; DB tạo tại
``device_farm/device_farm.db`` (cùng thư mục package). Mở bằng ``sqlite3 device_farm/device_farm.db``
hoặc DB Browser. Tuỳ chọn ``DEVICE_FARM_TRACE_SQLITE_PATH=/đường/dẫn/custom.db``.
Test batch xoá file cũ trước khi ghi lại (một lần chạy = một snapshot đầy đủ từ captures).
"""
from __future__ import annotations

import os
import re
import unicodedata
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List

import pytest

from db.seeds.scenario_templates import BUILTIN_TEMPLATES
from tasks.fb_extract import (
    _is_junk_parsed_comment_row,
    parse_fb_comments_from_xml,
    parse_fb_posts_from_xml,
)

CAPTURES_ROOT = Path(__file__).resolve().parent.parent / "captures"
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_TRACE_DB = _PACKAGE_ROOT / "device_farm.db"
_FB_MARKER = "com.facebook.katana"
# Chỉ ``*_extract_hierarchy.xml`` (không ``_pre_``): frame sau extract ổn định; ``_pre_`` hay là transition.
_STRICT_EVIDENCE_XML = re.compile(r"_extract_hierarchy\.xml$", re.IGNORECASE)
# Lưu DB trace / batch: comment chỉ từ frame feed/thread (tránh popup + bàn phím).
_COMMENT_PERSIST_XML = re.compile(
    r"(?:_extract_hierarchy|_scroll_down_hierarchy)\.xml$",
    re.IGNORECASE,
)


def _iter_xml() -> list[Path]:
    if not CAPTURES_ROOT.is_dir():
        return []
    return sorted(CAPTURES_ROOT.rglob("*.xml"))


_XML_PATHS = _iter_xml()


def _walk_steps(steps: List[Dict[str, Any]] | None) -> Generator[Dict[str, Any], None, None]:
    for s in steps or []:
        yield s
        if s.get("type") == "loop":
            yield from _walk_steps(s.get("steps"))
        for key in ("then", "else"):
            yield from _walk_steps(s.get(key))


def _fb_group_1h_spec() -> Dict[str, Any]:
    return next(t for t in BUILTIN_TEMPLATES if t["name"] == "fb_group_1h")


def _fb_group_1h_save_contract() -> Dict[str, Any]:
    """Trích cấu hình lưu (inline trên ``extract`` có ``collection``) — khớp seed fb_group_1h."""
    spec = _fb_group_1h_spec()
    variables = spec.get("variables") or {}
    post_save = next(
        s
        for s in _walk_steps(spec.get("steps"))
        if s.get("type") == "extract"
        and s.get("strategy") == "fb_posts"
        and s.get("collection")
    )
    comment_save = next(
        s
        for s in _walk_steps(spec.get("steps"))
        if s.get("type") == "extract"
        and s.get("strategy") == "fb_comments"
        and s.get("collection")
    )
    return {
        "variables": variables,
        "default_collection": str(variables.get("SAVE_COLLECTION", "fb_group_posts")),
        "post_save": post_save,
        "comment_save": comment_save,
    }


_G1H = _fb_group_1h_save_contract()


def test_fb_group_1h_template_save_matches_content_store_assumptions() -> None:
    """Extract có ``collection`` trong seed phải khớp field mà ``save_content_item`` + fb_extract dùng."""
    ps = _G1H["post_save"]
    assert ps.get("platform") == "facebook"
    assert ps.get("content_type") == "group_post"
    assert ps.get("dedupe_field") == "post_key"
    assert ps.get("collection")
    cs = _G1H["comment_save"]
    assert cs.get("platform") == "facebook"
    assert cs.get("content_type") == "comment"
    assert cs.get("dedupe_field") == "comment_key"
    assert cs.get("item_level") == 1
    assert cs.get("save_parent_id_var") == "_active_comment_parent_hash"
    assert cs.get("collection")


def test_fb_group_1h_template_extract_strategies_are_fb_posts_and_comments() -> None:
    spec = _fb_group_1h_spec()
    strategies = {
        s.get("strategy")
        for s in _walk_steps(spec.get("steps"))
        if s.get("type") == "extract" and s.get("strategy")
    }
    assert "fb_posts" in strategies
    assert "fb_comments" in strategies


def test_fb_group_1h_golden_posts_have_post_key_for_dedupe() -> None:
    """Dict post từ fb_extract phải có ``post_key`` (dedupe_field của save_extraction)."""
    path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-12_172100"
        / "step_001_extract_pre_hierarchy.xml"
    )
    if not path.is_file():
        pytest.skip("golden capture missing")
    xml = path.read_text(encoding="utf-8", errors="replace")
    posts = parse_fb_posts_from_xml(xml)
    assert posts
    for i, p in enumerate(posts):
        assert p.get("post_key"), f"post[{i}] missing post_key"
        assert p.get("stable_post_id"), f"post[{i}] missing stable_post_id"


def test_fb_group_1h_golden_comments_have_comment_key_when_parsed() -> None:
    path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-12_171940"
        / "step_002_scroll_down_hierarchy.xml"
    )
    feed_path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-12_171940"
        / "step_000_extract_pre_hierarchy.xml"
    )
    if not path.is_file() or not feed_path.is_file():
        pytest.skip("golden capture missing")
    xml = path.read_text(encoding="utf-8", errors="replace")
    feed = feed_path.read_text(encoding="utf-8", errors="replace")
    pid = parse_fb_posts_from_xml(feed)[0]["_pid"]
    rows = parse_fb_comments_from_xml(xml, parent_post_id=pid, max_items=200)
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    assert bodies
    for j, r in enumerate(bodies):
        assert r.get("comment_key"), f"comment[{j}] missing comment_key"


def _rel_id(path: Path) -> str:
    return str(path.relative_to(CAPTURES_ROOT))


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _xml_visible_corpus(xml: str) -> str:
    """Gom toàn bộ text hiển thị từ dump hierarchy (text + content-desc)."""
    from lxml import etree

    try:
        root = etree.fromstring(xml.encode("utf-8"))
    except etree.XMLSyntaxError:
        return ""
    parts: list[str] = []
    for node in root.iter("node"):
        t = node.get("text")
        if t:
            parts.append(t)
        d = node.get("content-desc")
        if d:
            parts.append(d)
    return "\n".join(parts)


def _assert_in_corpus(corpus_norm: str, needle: str, ctx: str) -> None:
    if not needle or not needle.strip():
        return
    n = _nfc(_collapse_ws(needle)).casefold()
    assert n in corpus_norm, f"{ctx}: không thấy trong XML dump → {needle[:120]!r}"


def _assert_body_snippet_in_corpus(corpus_norm: str, snip: str, ctx: str) -> None:
    """Body có thể bị gộp a11y / dư dấu — cần prefix đủ dài khớp dump."""
    if not snip or len(snip.strip()) < 12:
        return
    s = _nfc(_collapse_ws(snip)).casefold()
    s = re.sub(r"^[.\u2026…\s]+", "", s)  # bỏ .. … đầu dòng
    s = re.sub(
        r"\s+(video sound toggle|sound toggle|nhấn để phát|double tap to play)\s*$",
        "",
        s,
        flags=re.I,
    ).strip()
    if len(s) >= 12 and s in corpus_norm:
        return
    min_ok = min(36, max(24, len(s) // 2))
    for w in range(len(s), min_ok - 1, -1):
        if s[:w] in corpus_norm:
            return
    assert False, f"{ctx}: không có prefix body ≥{min_ok} ký tự khớp dump → {snip[:100]!r}"


_RE_FB_SHARE_PREFIX = re.compile(
    r"^\d{1,2}\s+thg\s+\d+\s*•\s*Chia\s+sẻ\s+với:\s*"
    r"(?:Công\s+khai\s+|Nhóm\s+công\s+khai[^,\n]+,\s*)",
    re.IGNORECASE,
)


def _body_snippet_for_evidence(body: str, *, min_len: int = 14) -> str:
    """Prefix nội dung sau khi bỏ timestamp đầu bài + hậu tố Xem thêm (so khớp dump đã gộp WS)."""
    b = (body or "").strip()
    for suf in (
        " Xem thêm",
        "… Xem thêm",
        " See more",
        "… See more",
        "see more",
    ):
        if b.lower().endswith(suf.lower()):
            b = b[: -len(suf)].rstrip()
            break
    b = _RE_FB_SHARE_PREFIX.sub("", b, count=1).strip()
    if "\n" in b:
        line0, rest = b.split("\n", 1)
        if re.match(r"^\d{1,2}\s+thg\s+\d+", line0, re.I) and "chia sẻ với" in line0.lower():
            b = rest.strip()
    b = _collapse_ws(b)
    if len(b) < min_len:
        return ""
    return b[: min(120, len(b))]


def _looks_like_group_suggestion_row(body: str) -> bool:
    """Hàng gợi ý nhóm / Remove … — parser đôi khi gộp nhầm, không bắt buộc substring."""
    b = (body or "").strip().casefold()
    return (
        b.startswith("remove ")
        or "thành viên •" in b
        or ("tham gia" in b and "thành viên" in b)
    )


def _looks_like_a11y_sticker_garbage(text: str) -> bool:
    if "nhãn dán avatar" in (text or "").casefold():
        return True
    if "hiển thị nhãn dán" in (text or "").casefold():
        return True
    return False


def _looks_like_merged_like_button_a11y(body: str) -> bool:
    b = (body or "").casefold()
    return "nút thích." in b and "bình luận" in b and "nhấn đúp" in b


def _assert_fb_posts_and_comments_match_dump(xml: str, rel: str) -> None:
    corpus_raw = _xml_visible_corpus(xml)
    corpus_norm = _nfc(_collapse_ws(corpus_raw)).casefold()

    posts = parse_fb_posts_from_xml(xml)
    for i, p in enumerate(posts):
        auth = (p.get("author") or "").strip()
        if auth and len(auth) >= 2:
            _assert_in_corpus(corpus_norm, auth, f"{rel} post[{i}] author")
        body = p.get("text") or ""
        snip = _body_snippet_for_evidence(str(body))
        if (
            snip
            and not _looks_like_group_suggestion_row(str(body))
            and not _looks_like_merged_like_button_a11y(str(body))
        ):
            _assert_body_snippet_in_corpus(corpus_norm, snip, f"{rel} post[{i}] body")
        elif (p.get("image_desc") or "").strip():
            idesc = (p.get("image_desc") or "").strip()[:80]
            _assert_in_corpus(corpus_norm, idesc, f"{rel} post[{i}] image_desc")
        prv = (p.get("comment_preview") or "").strip()
        if len(prv) >= 10:
            _assert_in_corpus(corpus_norm, _collapse_ws(prv[:120]), f"{rel} post[{i}] comment_preview")

    comments = parse_fb_comments_from_xml(xml)
    for j, c in enumerate(comments):
        if c.get("_type") == "post_stats":
            continue
        ca = (c.get("author") or "").strip()
        if ca and len(ca) >= 2:
            _assert_in_corpus(corpus_norm, ca, f"{rel} comment[{j}] author")
        ct = (c.get("text") or "").strip()
        if len(ct) >= 10 and not _looks_like_a11y_sticker_garbage(ct):
            if "thành viên •" in ct.casefold() and "tham gia" in ct.casefold():
                pass
            else:
                _assert_in_corpus(corpus_norm, _collapse_ws(ct[:140]), f"{rel} comment[{j}] text")
        for badge in c.get("badges") or []:
            if isinstance(badge, str) and badge.strip():
                _assert_in_corpus(corpus_norm, badge.strip(), f"{rel} comment[{j}] badge")


@pytest.mark.parametrize("xml_path", _XML_PATHS, ids=_rel_id)
def test_fb_capture_xml_parse_matches_on_screen_strings(xml_path: Path) -> None:
    """Dump FB ``step_*_extract_hierarchy.xml``: tên / body / badge phải có trong chính file.

    Bỏ qua ``_pre_``, bàn phím, chờ — hierarchy không phải frame feed cuối.
    """
    raw = xml_path.read_text(encoding="utf-8", errors="replace")
    if _FB_MARKER not in raw:
        return
    if not _STRICT_EVIDENCE_XML.search(xml_path.name):
        return
    _assert_fb_posts_and_comments_match_dump(raw, _rel_id(xml_path))


def _trace_sqlite_path() -> Path | None:
    """``DEVICE_FARM_TRACE_SQLITE=1`` → ``device_farm.db``; hoặc chỉ định ``DEVICE_FARM_TRACE_SQLITE_PATH``."""
    path_env = (os.environ.get("DEVICE_FARM_TRACE_SQLITE_PATH") or "").strip()
    if path_env:
        return Path(path_env).expanduser().resolve()
    flag = os.environ.get("DEVICE_FARM_TRACE_SQLITE", "").lower()
    if flag in ("1", "true", "yes"):
        return _DEFAULT_TRACE_DB.resolve()
    return None


def _sqlite_async_url(db_path: Path) -> str:
    # Một slash sau scheme: sqlite+aiosqlite:/// + absolute path (posix)
    return "sqlite+aiosqlite:///" + db_path.as_posix().replace(" ", "%20")


def _sqlite_engine_and_patch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    reset_trace_file: bool = False,
) -> tuple[object, str]:
    """Tạo engine SQLite + patch ``db.database.activity_session``.

    Returns ``(engine, label)`` với ``label`` ``memory`` hoặc đường dẫn file để log/trace.
    """
    import db.models  # noqa: F401 — register metadata
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    pytest.importorskip("aiosqlite")
    trace_path = _trace_sqlite_path()
    if trace_path is not None:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        if reset_trace_file and trace_path.is_file():
            trace_path.unlink()
        url = _sqlite_async_url(trace_path)
        label = str(trace_path)
    else:
        url = "sqlite+aiosqlite:///:memory:"
        label = ":memory:"

    engine = create_async_engine(url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def _patched_activity_session():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    monkeypatch.setattr("db.database.activity_session", _patched_activity_session)
    return engine, label


@pytest.mark.asyncio
async def test_all_capture_xmls_save_posts_and_comments_to_sqlite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parse captures → ``save_content_item`` như fb_group_1h, nhưng chỉ persist frame hợp lệ.

    Trước đây mọi ``*.xml`` (popup, dismiss, tap search, …) đều bị lưu → DB đầy author/body rác.
    Giờ: **post** chỉ từ ``*_extract_hierarchy.xml`` + Facebook; **comment** chỉ từ
    ``*_extract_hierarchy.xml`` / ``*_scroll_down_hierarchy.xml`` + Facebook, và bỏ hàng junk
    (``_is_junk_parsed_comment_row`` trong ``fb_extract``).
    """
    if not _XML_PATHS:
        pytest.skip("no captures tree")

    from services.content_store import compute_content_hash, save_content_item

    from db.database import Base

    ps = _G1H["post_save"]
    cs = _G1H["comment_save"]
    post_dedupe = ps.get("dedupe_field")
    comment_dedupe = cs.get("dedupe_field")
    assert post_dedupe and comment_dedupe

    engine, db_label = _sqlite_engine_and_patch(monkeypatch, reset_trace_file=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        coll = f"{_G1H['default_collection']}_pytest_{uuid.uuid4().hex[:10]}"
        saved = dup = err = 0
        for xml_path in _XML_PATHS:
            xml = xml_path.read_text(encoding="utf-8", errors="replace")
            rel = _rel_id(xml_path)
            tag = f"xml:{rel}"[:500]
            is_fb = _FB_MARKER in xml
            do_posts = is_fb and bool(_STRICT_EVIDENCE_XML.search(xml_path.name))
            do_comments = is_fb and bool(_COMMENT_PERSIST_XML.search(xml_path.name))

            parent_hash: str | None = None
            if is_fb:
                _plist = parse_fb_posts_from_xml(xml)
                if _plist:
                    parent_hash = compute_content_hash(dict(_plist[0]), dedupe_field=post_dedupe)

            if do_posts:
                for p in parse_fb_posts_from_xml(xml):
                    try:
                        r = await save_content_item(
                            dict(p),
                            collection=coll,
                            platform=ps.get("platform"),
                            content_type=ps.get("content_type"),
                            dedupe_field=post_dedupe,
                            device_serial="pytest-corpus",
                            tags=tag,
                        )
                        if r.get("saved"):
                            saved += 1
                        else:
                            dup += 1
                    except Exception:
                        err += 1

            if do_comments:
                for c in parse_fb_comments_from_xml(xml):
                    if c.get("_type") == "post_stats":
                        continue
                    if _is_junk_parsed_comment_row(c):
                        continue
                    try:
                        r = await save_content_item(
                            dict(c),
                            collection=coll,
                            platform=cs.get("platform"),
                            content_type=cs.get("content_type"),
                            dedupe_field=comment_dedupe,
                            device_serial="pytest-corpus",
                            tags=tag,
                            item_level=int(cs.get("item_level") or 0),
                            parent_id=parent_hash,
                        )
                        if r.get("saved"):
                            saved += 1
                        else:
                            dup += 1
                    except Exception:
                        err += 1

        assert saved + dup > 0, "expected at least one save or duplicate from corpus"
        assert err == 0, f"save_content_item errors: {err}"
        if db_label != ":memory:":
            print(f"\n[DEVICE_FARM_TRACE_SQLITE] saved corpus → {db_label} collection={coll!r}\n")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_row_matches_parsed_post_author_and_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sau khi lưu, đọc lại 1 row: author/body DB khớp dict parse (golden file có sẵn)."""
    from sqlalchemy import select

    from db.models.content import ContentItem
    from services.content_store import save_content_item

    path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-12_172100"
        / "step_001_extract_pre_hierarchy.xml"
    )
    if not path.is_file():
        pytest.skip("golden capture missing")

    from db.database import Base

    engine, db_label = _sqlite_engine_and_patch(monkeypatch, reset_trace_file=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        xml = path.read_text(encoding="utf-8", errors="replace")
        posts = parse_fb_posts_from_xml(xml)
        phan = next((p for p in posts if p.get("author") == "Phan Đình Long"), None)
        assert phan is not None
        ps = _G1H["post_save"]
        coll = f"{_G1H['default_collection']}_pytest_golden_{uuid.uuid4().hex[:8]}"
        r = await save_content_item(
            dict(phan),
            collection=coll,
            platform=ps.get("platform"),
            content_type=ps.get("content_type"),
            dedupe_field=ps.get("dedupe_field"),
            device_serial="pytest",
        )
        assert r.get("saved") is True
        from db.database import activity_session

        async with activity_session() as db:
            res = await db.execute(select(ContentItem).where(ContentItem.collection == coll).limit(1))
            row = res.scalar_one()
            assert row.author == "Phan Đình Long"
            assert row.body and "Open Claw" in row.body
            raw = row.raw_data or {}
            assert raw.get("author") == "Phan Đình Long"
        if db_label != ":memory:":
            print(f"\n[DEVICE_FARM_TRACE_SQLITE] golden row in {db_label} collection={coll!r}\n")
    finally:
        await engine.dispose()
