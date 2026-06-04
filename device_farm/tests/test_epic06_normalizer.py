"""Epic 06 DF-T-06-007: unified content normalizer."""
from __future__ import annotations

import pytest

from services.content.errors import NormalizationError
from services.content.normalizer import normalize
from services.content.registry import seed_registry


@pytest.fixture(autouse=True)
def _registry():
    seed_registry()
    yield


class TestContentNormalizer:
    def test_fb_post_hierarchy_and_ai_same_columns(self):
        hierarchy = {
            "text": "Hello",
            "author": "Nam Nguyễn",
            "likes": 42,
            "permalink": "https://facebook.com/post/1",
            "resource_id": "node-99",
        }
        ai = {
            "text_content": "Hello",
            "author_name": "Nam Nguyễn",
            "likes_count": 42,
            "url": "https://facebook.com/post/1",
            "confidence": 0.98,
        }
        h = normalize(hierarchy, "fb_post")
        a = normalize(ai, "fb_post")
        assert h.text_content == a.text_content == "Hello"
        assert h.author_name == a.author_name == "Nam Nguyễn"
        assert h.counters.likes == a.counters.likes == 42
        assert h.permalink == a.permalink
        assert h.content_type == "fb_post"
        assert "resource_id" in h.raw_data
        assert "confidence" in a.raw_data

    def test_parse_k_suffix(self):
        out = normalize(
            {"text": "Hi", "likes": "1.2K", "permalink": "https://x/y"},
            "fb_post",
        )
        assert out.counters.likes == 1200

    def test_extra_fields_in_raw_data(self):
        out = normalize(
            {
                "text": "Hi",
                "permalink": "https://x/y",
                "fb_internal_story_id": "abc123",
            },
            "fb_post",
        )
        assert out.raw_data["fb_internal_story_id"] == "abc123"

    def test_ig_profile_schema(self):
        out = normalize(
            {
                "username": "chef",
                "follower_count": "1.5M",
                "following_count": 200,
                "bio": "food",
            },
            "ig_profile",
        )
        assert out.counters.followers == 1_500_000
        assert out.author_id == "chef"

    def test_missing_required_raises(self):
        with pytest.raises(NormalizationError) as exc:
            normalize({}, "fb_post")
        assert exc.value.code == "NORMALIZATION_MISSING_FIELDS"
