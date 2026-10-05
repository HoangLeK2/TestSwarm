"""Unit tests for DF-010: Content Pipeline.

Tests cover:
  - Content hash computation (dedup, unicode, determinism)
  - _safe_int metric parsing (K/M suffixes, edge cases)
  - Content store save logic (dedup, field mapping)
  - CSV/JSON export writing
  - Scenario step: save_extraction
  - Content schemas
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.database import Base
from db.models.content import ContentItem
from db.crud.content import query_content
from tenancy.context import tenant_context
from services.content_store import (
    _first_present,
    _normalize_media_urls,
    compute_content_hash,
    _parse_content_date,
    _safe_int,
)


# ── Content Hash ──────────────────────────────────────────────────────────────


class TestComputeContentHash:
    def test_deterministic(self):
        data = {"author": "John", "content": "Hello world"}
        h1 = compute_content_hash(data)
        h2 = compute_content_hash(data)
        assert h1 == h2

    def test_different_data_different_hash(self):
        h1 = compute_content_hash({"text": "Hello"})
        h2 = compute_content_hash({"text": "World"})
        assert h1 != h2

    def test_key_order_independent(self):
        h1 = compute_content_hash({"a": 1, "b": 2})
        h2 = compute_content_hash({"b": 2, "a": 1})
        assert h1 == h2

    def test_dedupe_field(self):
        data = {"id": "123", "text": "Hello"}
        h1 = compute_content_hash(data, dedupe_field="id")
        # Changing text shouldn't change hash when dedup on id
        data2 = {"id": "123", "text": "Different"}
        h2 = compute_content_hash(data2, dedupe_field="id")
        assert h1 == h2

    def test_dedupe_field_missing_falls_back(self):
        data = {"text": "Hello"}
        h1 = compute_content_hash(data, dedupe_field="nonexistent")
        h2 = compute_content_hash(data)
        assert h1 == h2  # fallback to full hash

    def test_unicode_nfc_normalized(self):
        # é as composed vs decomposed
        data1 = {"text": "caf\u00e9"}           # composed
        data2 = {"text": "cafe\u0301"}           # decomposed
        h1 = compute_content_hash(data1)
        h2 = compute_content_hash(data2)
        assert h1 == h2  # NFC normalization makes them equal

    def test_hash_is_sha256_hex(self):
        h = compute_content_hash({"test": True})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_empty_data(self):
        h = compute_content_hash({})
        assert len(h) == 64

    def test_nested_data(self):
        data = {"post": {"author": "A", "likes": [1, 2, 3]}}
        h = compute_content_hash(data)
        assert len(h) == 64


# ── _safe_int ─────────────────────────────────────────────────────────────────


class TestSafeInt:
    def test_none(self):
        assert _safe_int(None) is None

    def test_int(self):
        assert _safe_int(42) == 42

    def test_float(self):
        assert _safe_int(3.7) == 3

    def test_string_number(self):
        assert _safe_int("123") == 123

    def test_string_with_comma(self):
        assert _safe_int("1,234") == 1234

    def test_k_suffix(self):
        assert _safe_int("1.2K") == 1200

    def test_k_suffix_uppercase(self):
        assert _safe_int("45K") == 45000

    def test_m_suffix(self):
        assert _safe_int("1.5M") == 1500000

    def test_empty_string(self):
        assert _safe_int("") is None

    def test_garbage(self):
        assert _safe_int("abc") is None

    def test_zero(self):
        assert _safe_int(0) == 0
        assert _safe_int("0") == 0


class TestParseContentDate:
    def test_iso_datetime(self):
        dt = _parse_content_date("2026-04-15T10:30:00Z")
        assert isinstance(dt, datetime)
        assert dt.tzinfo is not None
        assert dt.year == 2026 and dt.month == 4 and dt.day == 15

    def test_dd_mm_yyyy(self):
        dt = _parse_content_date("15/04/2026")
        assert dt == datetime(2026, 4, 15, tzinfo=timezone.utc)

    def test_relative_vietnamese(self):
        dt = _parse_content_date("2 giờ trước")
        assert isinstance(dt, datetime)

    def test_invalid_returns_none(self):
        assert _parse_content_date("khong phai ngay") is None

    def test_lowercase_z_timezone(self):
        dt = _parse_content_date("2026-04-15T10:30:00z")
        assert isinstance(dt, datetime)
        assert dt.tzinfo is not None

    def test_naive_datetime_becomes_utc(self):
        dt = _parse_content_date(datetime(2026, 4, 15, 10, 30, 0))
        assert isinstance(dt, datetime)
        assert dt.tzinfo == timezone.utc


class TestFieldHelpers:
    def test_first_present_keeps_zero(self):
        data = {"likes_count": 0, "likes": "1.2K"}
        assert _first_present(data, "likes_count", "likes") == 0

    def test_normalize_media_urls_string_json(self):
        value = '["https://a.example/x.jpg","https://b.example/y.jpg"]'
        out = _normalize_media_urls(value)
        assert out == ["https://a.example/x.jpg", "https://b.example/y.jpg"]


# ── Schema Validation ─────────────────────────────────────────────────────────


class TestContentSchemas:
    def test_save_content_body(self):
        from api.schemas.content import SaveContentBody
        body = SaveContentBody(
            data={"author": "test", "content": "hello"},
            collection="posts",
            platform="instagram",
            content_type="ig_media",
        )
        assert body.collection == "posts"
        assert body.content_type == "ig_media"

    def test_content_query_defaults(self):
        from api.schemas.content import ContentQueryParams
        q = ContentQueryParams()
        assert q.limit == 50
        assert q.offset == 0
        assert q.collection is None

    def test_content_stats_out(self):
        from api.schemas.content import ContentStatsOut
        stats = ContentStatsOut(
            total_items=100,
            by_platform={"instagram": 60, "tiktok": 40},
            by_collection={"default": 100},
        )
        assert stats.total_items == 100


# ── Scenario Step Types Registered ────────────────────────────────────────────


class TestScenarioStepRegistration:
    def test_save_extraction_registered(self):
        from common.scenario_schema import SCENARIO_STEP_TYPES, STEP_SCHEMA
        assert "save_extraction" in SCENARIO_STEP_TYPES
        assert "save_extraction" in STEP_SCHEMA
        assert "data_var" in STEP_SCHEMA["save_extraction"]["required"]

    def test_all_extraction_steps_registered(self):
        from common.scenario_schema import SCENARIO_STEP_TYPES, STEP_SCHEMA
        for st in [
            "extract_text_hierarchy", "extract_text_ocr",
            "extract_text_ai", "extract_screen_data", "save_extraction",
        ]:
            assert st in SCENARIO_STEP_TYPES, f"{st} missing"
            assert st in STEP_SCHEMA, f"{st} schema missing"


# ── Content Model ─────────────────────────────────────────────────────────────


class TestContentModel:
    def test_to_dict(self):
        from db.models.content import ContentItem
        from datetime import datetime

        item = ContentItem(
            id="test-id",
            collection="posts",
            platform="instagram",
            content_type="post",
            body="Hello world",
            author="John",
            likes_count=42,
            extracted_at=datetime(2026, 3, 28, 12, 0, 0),
        )
        d = item.to_dict()
        assert d["id"] == "test-id"
        assert d["platform"] == "instagram"
        assert d["body"] == "Hello world"
        assert d["likes_count"] == 42
        assert "2026-03-28" in d["extracted_at"]

    def test_explicit_values(self):
        from db.models.content import ContentItem
        item = ContentItem(
            collection="test", content_type="video",
            tags="tag1", content_hash="abc123",
        )
        assert item.collection == "test"
        assert item.content_type == "video"
        assert item.tags == "tag1"


@pytest.mark.asyncio
async def test_query_content_search_matches_author_for_posts_and_comments():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    try:
        async with session_factory() as db:
            db.add_all(
                [
                    ContentItem(
                        org_id="org-1",
                        collection="crawl",
                        platform="instagram",
                        content_type="ig_media",
                        body="Question about model choice",
                        author="Nguoi tham gia an danh",
                        content_hash="post-hash",
                    ),
                    ContentItem(
                        org_id="org-1",
                        collection="crawl",
                        platform="instagram",
                        content_type="ig_comment",
                        body="Short answer",
                        author="Hoang Thanh Tung",
                        content_hash="comment-hash",
                        parent_id="post-hash",
                        item_level=1,
                    ),
                ]
            )
            await db.commit()

        async with session_factory() as db:
            with tenant_context("org-1"):
                posts, post_total = await query_content(
                    db,
                    collection="crawl",
                    content_type="ig_media",
                    search="tham gia",
                )
                comments, comment_total = await query_content(
                    db,
                    collection="crawl",
                    content_type="ig_comment",
                    search="Hoang",
                )

        assert post_total == 1
        assert [item.content_hash for item in posts] == ["post-hash"]
        assert comment_total == 1
        assert [item.content_hash for item in comments] == ["comment-hash"]
    finally:
        await engine.dispose()
