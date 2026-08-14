from __future__ import annotations

from typing import Any

from services.social_ext.contract import (
    ExtractionStrategySchema,
    PlatformContentType,
    PlatformContentTypeSchema,
    PlatformExtension,
    PlatformScenarioLib,
)


class AgentBootDelegatedParser:
    """Parser facade documenting that raw extraction runs in agent-boot."""

    def parse(self, snapshot: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
        raise RuntimeError("Facebook raw parsing is delegated to agent-boot extra_data")


class MetadataOnlyHandler:
    """Registry handler marker; runtime dispatch remains in scenario step handlers."""

    def __init__(self, step_type: str) -> None:
        self.step_type = step_type

    def execute(self, ctx: Any, step: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "code": "HANDLER_METADATA_ONLY",
            "step_type": self.step_type,
        }


FACEBOOK_STEP_TYPES = [
    "content_interaction",
    "connection_request",
    "community_membership",
    "fb_like_post",
    "fb_comment_post",
    "fb_share_post",
    "fb_follow_user",
    "fb_tap_comment_button",
    "fb_find_comment_button",
    "fb_tap_comment_target",
    "fb_apply_comment_filter",
    "fb_select_people_profile",
    "fb_connect_visible_people",
    "fb_select_post_target",
    "fb_scan_posts_interact",
    "social_open_author_from_post_match",
]

FACEBOOK_ALIASES = {
    "tap_fb_comment_button": "fb_tap_comment_button",
}


def build_facebook_extension() -> PlatformExtension:
    strategies = {
        "fb_posts": ExtractionStrategySchema(
            name="fb_posts",
            content_type="fb_post",
            status="Active",
        ),
        "fb_comments": ExtractionStrategySchema(
            name="fb_comments",
            content_type="fb_comment",
            status="Active",
        ),
    }
    return PlatformExtension(
        name="facebook",
        version="1.0.0",
        coverage="L2 Active",
        parser=AgentBootDelegatedParser(),
        handlers={step: MetadataOnlyHandler(step) for step in FACEBOOK_STEP_TYPES},
        aliases=FACEBOOK_ALIASES,
        enabled_by_default=True,
        scenario_lib=PlatformScenarioLib(
            step_types=FACEBOOK_STEP_TYPES,
            extraction_strategies=list(strategies),
            strategies=strategies,
        ),
        content_schema=PlatformContentTypeSchema(
            platform="facebook",
            parser_module="agent-boot/relay/extra_data/parsers/facebook",
            content_types=[
                PlatformContentType(
                    code="fb_post",
                    object_type="post",
                    description="Facebook post extracted and persisted by agent-boot extra_data",
                ),
                PlatformContentType(
                    code="fb_comment",
                    object_type="comment",
                    description="Facebook comment extracted and persisted by agent-boot extra_data",
                ),
            ],
        ),
    )
