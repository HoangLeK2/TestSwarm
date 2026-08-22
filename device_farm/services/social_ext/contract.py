from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

CONTRACT_VERSION = "2.0.0"

# Platform-neutral scenario vocabulary. Step types are public API and never carry
# a platform name — the platform travels as the ``platform`` field on the step.
# Platform-specific knowledge lives in the extension registered here and in the
# ``_flow_<platform>_*`` implementations inside agent-boot.
SOCIAL_STEP_TYPES: frozenset[str] = frozenset(
    {
        "platform_session_gate",
        "lease_connection_candidate",
        "social_select_target",
        "social_connect_visible_people",
        "social_find_comment_button",
        "social_tap_comment_target",
        "social_apply_comment_filter",
        "social_open_comments",
        "social_scan_posts_interact",
        "social_open_author_from_post_match",
        "social_open_commenter_from_post_match",
        "social_sync_connections",
        "content_interaction",
        "connection_request",
        "community_membership",
    }
)

# Social steps that act *as* an account (mutate state or need credentials), so a
# campaign using them must bind an account before dispatch. Read-only crawl steps
# (opening a comment sheet, applying a filter, the session gate) are deliberately
# excluded — they work without a bound account.
SOCIAL_ACCOUNT_BOUND_STEP_TYPES: frozenset[str] = frozenset(
    {
        "lease_connection_candidate",
        "social_select_target",
        "social_connect_visible_people",
        "social_scan_posts_interact",
        "social_open_author_from_post_match",
        "social_open_commenter_from_post_match",
        "social_sync_connections",
        "content_interaction",
        "connection_request",
        "community_membership",
    }
)

# Entities an ``extract`` step can collect. Replaces the old platform-prefixed
# strategy names (fb_posts / ig_posts / …) — the platform is a separate field.
SOCIAL_ENTITIES: frozenset[str] = frozenset(
    {"posts", "comments", "groups", "pages", "text_nodes"}
)


@runtime_checkable
class PlatformParser(Protocol):
    """Parser boundary for platform XML/screenshot extraction.

    Epic 08 keeps raw hierarchy parsing and raw_data persistence in agent-boot.
    Device Farm extensions may declare this interface, but active edge parsers
    are delegated to ``agent-boot/relay/extra_data``.
    """

    def parse(self, snapshot: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
        ...


@runtime_checkable
class PlatformHandler(Protocol):
    """Scenario step handler contract for platform-specific actions."""

    def execute(self, ctx: Any, step: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True, slots=True)
class PlatformContentType:
    code: str
    object_type: str
    storage_owner: str = "agent-boot"
    raw_data_owner: str = "agent-boot"
    persisted_in_device_farm: bool = False
    description: str = ""


@dataclass(frozen=True, slots=True)
class PlatformContentTypeSchema:
    platform: str
    content_types: list[PlatformContentType] = field(default_factory=list)
    parser_module: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionStrategySchema:
    entity: str
    content_type: str
    storage_owner: str = "agent-boot"
    raw_data_owner: str = "agent-boot"
    persisted_in_device_farm: bool = False
    status: str = "Active"


@dataclass(frozen=True, slots=True)
class PlatformScenarioLib:
    """Which platform-neutral steps and entities this platform can actually run.

    ``step_types`` must be a subset of :data:`SOCIAL_STEP_TYPES` and ``entities``
    a subset of :data:`SOCIAL_ENTITIES`; both are validated on register().
    """

    step_types: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    strategies: dict[str, ExtractionStrategySchema] = field(default_factory=dict)
    templates: list[dict[str, Any]] = field(default_factory=list)


# How a connection is formed on this platform. The candidate lifecycle differs:
# ``friend_request`` needs the other side to accept, so a sent request sits in
# ``request_pending`` until reconciled; ``follow`` is unilateral and lands in
# ``connected`` the moment the tap verifies. Code must branch on this instead of
# assuming Facebook's two-sided model.
CONNECTION_KINDS: frozenset[str] = frozenset({"friend_request", "follow"})
DEFAULT_CONNECTION_KIND = "friend_request"


@dataclass(frozen=True, slots=True)
class PlatformExtension:
    name: str
    version: str
    coverage: str
    scenario_lib: PlatformScenarioLib
    content_schema: PlatformContentTypeSchema
    parser: PlatformParser | None = None
    handlers: dict[str, PlatformHandler] = field(default_factory=dict)
    enabled_by_default: bool = False
    lifecycle: str = "loaded"
    min_contract_version: str = CONTRACT_VERSION
    connection_kind: str = DEFAULT_CONNECTION_KIND
