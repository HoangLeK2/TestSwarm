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

import csv
import io
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.content_store import compute_content_hash, _safe_int


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


# ── Content Export CSV/JSON Writing ───────────────────────────────────────────


class TestExportWriting:
    def test_write_csv(self):
        from services.content_export import _write_csv

        # Create mock items with to_dict
        items = [
            MagicMock(to_dict=lambda: {
                "id": "1", "collection": "test", "platform": "facebook",
                "content_type": "post", "author": "John", "title": "",
                "body": "Hello world", "url": "", "likes_count": 10,
                "comments_count": 5, "shares_count": 0, "views_count": 100,
                "tags": "test", "device_serial": "dev1", "campaign_id": None,
                "extracted_at": "2026-03-28T12:00:00",
            }),
        ]

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            path = f.name
        try:
            _write_csv(path, items)
            with open(path, "r") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["platform"] == "facebook"
            assert rows[0]["body"] == "Hello world"
            assert rows[0]["likes_count"] == "10"
        finally:
            os.unlink(path)

    def test_write_json(self):
        from services.content_export import _write_json

        items = [
            MagicMock(to_dict=lambda: {
                "id": "1", "platform": "tiktok", "body": "Video content",
            }),
        ]

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            _write_json(path, items)
            with open(path, "r") as f:
                data = json.load(f)
            assert len(data) == 1
            assert data[0]["platform"] == "tiktok"
        finally:
            os.unlink(path)


# ── Schema Validation ─────────────────────────────────────────────────────────


class TestContentSchemas:
    def test_save_content_body(self):
        from api.schemas.content import SaveContentBody
        body = SaveContentBody(
            data={"author": "test", "content": "hello"},
            collection="fb_posts",
            platform="facebook",
        )
        assert body.collection == "fb_posts"
        assert body.content_type == "post"  # default

    def test_export_request(self):
        from api.schemas.content import ExportRequest
        req = ExportRequest(collection="test", format="csv")
        assert req.format == "csv"
        assert req.filters == {}

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
            by_platform={"facebook": 60, "tiktok": 40},
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
            collection="fb_posts",
            platform="facebook",
            content_type="post",
            body="Hello world",
            author="John",
            likes_count=42,
            extracted_at=datetime(2026, 3, 28, 12, 0, 0),
        )
        d = item.to_dict()
        assert d["id"] == "test-id"
        assert d["platform"] == "facebook"
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
