"""Tests for legacy → platform-qualified content_type migration (Epic 06)."""
from __future__ import annotations

from services.content.legacy_type_map import (
    default_content_type_for_strategy,
    migrate_content_type_in_step,
    migrate_content_type_in_steps,
    qualify_content_type,
)


def test_qualify_static_legacy_names():
    assert qualify_content_type("group_post", platform="facebook") == "fb_post"
    assert qualify_content_type("profile_post", platform="facebook") == "fb_post"


def test_qualify_generic_with_platform():
    assert qualify_content_type("post", platform="facebook") == "fb_post"
    assert qualify_content_type("comment", platform="facebook") == "fb_comment"
    assert qualify_content_type("video", platform="tiktok") == "tiktok_video"
    assert qualify_content_type("post", platform="instagram") == "ig_media"


def test_qualify_generic_with_strategy():
    assert qualify_content_type("comment", strategy="fb_comments") == "fb_comment"
    assert qualify_content_type("post", strategy="fb_posts") == "fb_post"
    assert qualify_content_type("video", strategy="tiktok_posts") == "tiktok_video"


def test_qualify_preserves_registered_codes():
    assert qualify_content_type("fb_post") == "fb_post"
    assert qualify_content_type("tiktok_comment") == "tiktok_comment"


def test_default_content_type_for_strategy():
    assert default_content_type_for_strategy("fb_posts", {}) == "fb_post"
    assert default_content_type_for_strategy("fb_comments", {}) == "fb_comment"
    assert default_content_type_for_strategy("text_nodes", {}) == "text"
    assert (
        default_content_type_for_strategy(
            "fb_posts",
            {"content_type": "group_post", "platform": "facebook"},
        )
        == "fb_post"
    )


def test_migrate_nested_steps():
    steps = [
        {
            "type": "loop",
            "steps": [
                {
                    "type": "extract",
                    "strategy": "fb_posts",
                    "platform": "facebook",
                    "content_type": "group_post",
                },
                {
                    "type": "social_open_comments",
                    "then": [
                        {
                            "type": "extract",
                            "strategy": "fb_comments",
                            "platform": "facebook",
                            "content_type": "comment",
                        }
                    ],
                },
            ],
        }
    ]
    assert migrate_content_type_in_steps(steps) is True
    assert steps[0]["steps"][0]["content_type"] == "fb_post"
    assert steps[0]["steps"][1]["then"][0]["content_type"] == "fb_comment"


def test_migrate_step_noop_when_already_qualified():
    step = {"type": "extract", "content_type": "fb_post", "platform": "facebook"}
    assert migrate_content_type_in_step(step) is False
    assert step["content_type"] == "fb_post"
