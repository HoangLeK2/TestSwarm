"""Tests for platform-qualified content_type migration (Epic 06)."""
from __future__ import annotations

from services.content.legacy_type_map import (
    default_content_type_for_strategy,
    migrate_content_type_in_step,
    migrate_content_type_in_steps,
    qualify_content_type,
)


def test_qualify_generic_with_platform():
    assert qualify_content_type("post", platform="instagram") == "ig_media"
    assert qualify_content_type("comment", platform="instagram") == "ig_comment"
    assert qualify_content_type("video", platform="tiktok") == "tiktok_video"
    assert qualify_content_type("thread", platform="threads") == "threads_post"


def test_qualify_generic_with_strategy():
    assert qualify_content_type("comment", strategy="ig_comments") == "ig_comment"
    assert qualify_content_type("post", strategy="ig_posts") == "ig_media"
    assert qualify_content_type("video", strategy="tiktok_posts") == "tiktok_video"
    assert qualify_content_type("comment", strategy="threads_comments") == "threads_comment"


def test_qualify_preserves_registered_codes():
    assert qualify_content_type("ig_media") == "ig_media"
    assert qualify_content_type("tiktok_comment") == "tiktok_comment"
    assert qualify_content_type("threads_post") == "threads_post"


def test_default_content_type_for_strategy():
    assert default_content_type_for_strategy("ig_posts", {}) == "ig_media"
    assert default_content_type_for_strategy("ig_comments", {}) == "ig_comment"
    assert default_content_type_for_strategy("text_nodes", {}) == "text"
    assert (
        default_content_type_for_strategy(
            "threads_posts",
            {"content_type": "post", "platform": "threads"},
        )
        == "threads_post"
    )


def test_migrate_nested_steps():
    steps = [
        {
            "type": "loop",
            "steps": [
                {
                    "type": "extract",
                    "strategy": "ig_posts",
                    "platform": "instagram",
                    "content_type": "post",
                },
                {
                    "type": "open_comments",
                    "then": [
                        {
                            "type": "extract",
                            "strategy": "threads_comments",
                            "platform": "threads",
                            "content_type": "comment",
                        }
                    ],
                },
            ],
        }
    ]
    assert migrate_content_type_in_steps(steps) is True
    assert steps[0]["steps"][0]["content_type"] == "ig_media"
    assert steps[0]["steps"][1]["then"][0]["content_type"] == "threads_comment"


def test_migrate_step_noop_when_already_qualified():
    step = {"type": "extract", "content_type": "ig_media", "platform": "instagram"}
    assert migrate_content_type_in_step(step) is False
    assert step["content_type"] == "ig_media"
