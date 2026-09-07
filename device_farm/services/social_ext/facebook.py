from __future__ import annotations

from typing import Any

from services.social_ext.contract import (
    ExtractionStrategySchema,
    PlatformCapabilitySupport,
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


# Platform-neutral step types Facebook implements. Names never carry a platform;
# the Facebook-specific behaviour lives in agent-boot's ``_flow_fb_*`` handlers.
FACEBOOK_STEP_TYPES = [
    "platform_session_gate",
    "lease_connection_candidate",
    "content_interaction",
    "connection_request",
    "community_membership",
    "social_select_target",
    "social_connect_visible_people",
    "social_open_comments",
    "social_find_comment_button",
    "social_tap_comment_target",
    "social_apply_comment_filter",
    "social_scan_posts_interact",
    "social_open_author_from_post_match",
    "social_open_commenter_from_post_match",
    "social_sync_connections",
]

FACEBOOK_ENTITIES = ["posts", "comments", "groups", "pages"]

FACEBOOK_CAPABILITIES = {
    "platform.session.check": PlatformCapabilitySupport(
        facets={
            "session_surface": "facebook_app",
            "login_state_markers": "facebook_readiness",
        },
    ),
    "social.target.lease": PlatformCapabilitySupport(
        execution_mode="generic_recipe",
        generic_recipes=["database_lease"],
        facets={"connection_kind": "friend_request"},
    ),
    "social.target.select": PlatformCapabilitySupport(
        facets={
            "target_type": "person_or_post",
            "locator_strategy": "facebook_hierarchy",
            "profile_surface": "facebook_profile",
            "post_surface": "facebook_post_detail",
        },
    ),
    "social.visible_people.connect": PlatformCapabilitySupport(
        facets={
            "connection_kind": "friend_request",
            "common_context_markers": "mutual_friends_or_group",
        },
    ),
    "social.comments.open": PlatformCapabilitySupport(
        facets={
            "comment_surface": "overlay",
            "comment_filter_modes": ["most_relevant", "newest", "all_comments"],
            "locator_strategy": "facebook_comment_button",
        },
        provider_fields=[
            {
                "name": "comment_filter",
                "type": "select",
                "label": "Comment ordering",
                "group": "provider",
                "advanced": True,
                "options": ["most_relevant", "newest", "all_comments"],
            }
        ],
    ),
    "social.content.scan": PlatformCapabilitySupport(
        facets={
            "content_surface": "feed_or_group",
            "comment_surface": "overlay",
            "profile_surface": "facebook_profile",
        },
    ),
    "social.content.interact": PlatformCapabilitySupport(
        facets={
            "content_actions": ["like", "comment", "share"],
            "comment_surface": "overlay",
        },
    ),
    "social.connection.request": PlatformCapabilitySupport(
        facets={
            "connection_kind": "friend_request",
            "profile_surface": "facebook_profile",
        },
    ),
    "social.community.membership": PlatformCapabilitySupport(
        facets={
            "community_surface": "group",
            "membership_state": "member_or_pending",
        },
    ),
    "social.connections.sync": PlatformCapabilitySupport(
        facets={"connection_kind": "friend_request", "metric": "friends"},
    ),
}


def build_facebook_extension() -> PlatformExtension:
    strategies = {
        "posts": ExtractionStrategySchema(
            entity="posts",
            content_type="fb_post",
            status="Active",
        ),
        "comments": ExtractionStrategySchema(
            entity="comments",
            content_type="fb_comment",
            status="Active",
        ),
    }
    return PlatformExtension(
        name="facebook",
        version="2.0.0",
        coverage="L2 Active",
        connection_kind="friend_request",
        parser=AgentBootDelegatedParser(),
        handlers={step: MetadataOnlyHandler(step) for step in FACEBOOK_STEP_TYPES},
        enabled_by_default=True,
        scenario_lib=PlatformScenarioLib(
            step_types=FACEBOOK_STEP_TYPES,
            entities=FACEBOOK_ENTITIES,
            strategies=strategies,
            capabilities=FACEBOOK_CAPABILITIES,
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
