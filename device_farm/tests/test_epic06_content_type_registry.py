"""Epic 06 DF-T-06-001: content type registry."""
from __future__ import annotations

import pytest

from services.content.errors import ContentTypeError
from services.content.registry import (
    ContentTypeEntry,
    ContentTypeRegistry,
    require_valid_content_type,
    seed_registry,
    validate_content_type,
)


@pytest.fixture(autouse=True)
def _registry():
    seed_registry()
    yield
    seed_registry([])


class TestContentTypeRegistry:
    def test_validate_fb_post_ok(self):
        ok, reason = validate_content_type("fb_post")
        assert ok is True
        assert reason is None

    def test_validate_generic_post_rejected(self):
        ok, reason = validate_content_type("post")
        assert ok is False
        assert reason == "GENERIC"

    def test_validate_unregistered(self):
        ok, reason = validate_content_type("youtube_short")
        assert ok is False
        assert reason == "NOT_REGISTERED"

    def test_require_valid_raises_generic(self):
        with pytest.raises(ContentTypeError) as exc:
            require_valid_content_type("comment")
        assert exc.value.code == "CONTENT_TYPE_GENERIC_REJECTED"
        assert "fb_comment" in exc.value.details.get("suggestions", [])

    def test_list_returns_nine_types(self):
        from services.content.registry import get_registry

        items = get_registry().list()
        assert len(items) == 9
        codes = {i.code for i in items}
        assert "fb_post" in codes
        assert "ig_profile" in codes

    def test_deprecated_type_rejected(self):
        seed_registry(
            [
                ContentTypeEntry("fb_post", "facebook", "post", "deprecated", [], "old"),
            ]
        )
        with pytest.raises(ContentTypeError) as exc:
            require_valid_content_type("fb_post")
        assert exc.value.code == "CONTENT_TYPE_DEPRECATED"

    def test_registry_not_initialized(self):
        reg = ContentTypeRegistry()
        with pytest.raises(RuntimeError):
            reg.validate("fb_post")
