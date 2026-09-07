from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from services.social_ext.contract import SOCIAL_CAPABILITY_SCHEMAS
from services.social_ext.registry import SocialPlatformRegistry, get_social_platform_registry

CATALOG_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class NodeFieldSchema:
    name: str
    type: str
    label: str
    group: str
    required: bool = False
    advanced: bool = False
    description: str = ""
    placeholder: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    visible_when: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class NodePreset:
    id: str
    display_name: str
    description: str
    runtime_step_type: str
    defaults: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NodeDefinition:
    node_type: str
    runtime_step_type: str
    schema_version: int
    display_name: str
    description: str
    category: str
    capability_id: str | None = None
    fields: list[NodeFieldSchema] = field(default_factory=list)
    presets: list[NodePreset] = field(default_factory=list)
    legacy: dict[str, Any] = field(default_factory=dict)


def _social_action_fields() -> list[NodeFieldSchema]:
    return [
        NodeFieldSchema(
            name="platform",
            type="provider",
            label="Run on",
            group="runTarget",
            required=True,
            description="Provider/app adapter used to execute this semantic action.",
        ),
        NodeFieldSchema(
            name="require_verified_target",
            type="resourceRef",
            label="Target content/profile",
            group="target",
            description="Verified target variable produced by a select/lease step.",
            placeholder="_people_target",
        ),
        NodeFieldSchema(
            name="action",
            type="select",
            label="Action",
            group="content",
            required=True,
            depends_on=["platform"],
        ),
        NodeFieldSchema(
            name="comment_text",
            type="textarea",
            label="Comment text",
            group="content",
            required=True,
            placeholder="${COMMENT_TEXT}",
            visible_when={"action": "comment"},
            depends_on=["action"],
        ),
        NodeFieldSchema(
            name="timeout",
            type="number",
            label="Find button timeout",
            group="options",
            advanced=True,
        ),
        NodeFieldSchema(
            name="verify_timeout",
            type="number",
            label="Verify timeout",
            group="options",
            advanced=True,
        ),
    ]


def _catalog_definitions() -> list[NodeDefinition]:
    return [
        NodeDefinition(
            node_type="content_interaction",
            runtime_step_type="content_interaction",
            schema_version=2,
            capability_id="social.content.interact",
            display_name="Engage with Content",
            description="React, comment, or share the currently verified content target.",
            category="Engagement",
            fields=_social_action_fields(),
            presets=[
                NodePreset(
                    id="content.reaction.add",
                    display_name="React to Content",
                    description="Add a provider-supported reaction to selected content.",
                    runtime_step_type="content_interaction",
                    defaults={"type": "content_interaction", "action": "like", "platform": "auto"},
                ),
                NodePreset(
                    id="content.comment.create",
                    display_name="Add Comment",
                    description="Write a comment on selected content.",
                    runtime_step_type="content_interaction",
                    defaults={
                        "type": "content_interaction",
                        "action": "comment",
                        "platform": "auto",
                        "comment_text": "${COMMENT_TEXT}",
                    },
                ),
                NodePreset(
                    id="content.share.create",
                    display_name="Share / Repost",
                    description="Share provider-supported content.",
                    runtime_step_type="content_interaction",
                    defaults={"type": "content_interaction", "action": "share", "platform": "auto"},
                ),
            ],
        ),
        NodeDefinition(
            node_type="extract",
            runtime_step_type="extract",
            schema_version=2,
            capability_id="content.extract",
            display_name="Extract Content",
            description="Collect posts, comments, pages, groups, or screen text from the selected provider.",
            category="Data",
            fields=[
                NodeFieldSchema(
                    name="platform",
                    type="provider",
                    label="Run on",
                    group="runTarget",
                    required=True,
                ),
                NodeFieldSchema(
                    name="entity",
                    type="select",
                    label="What to extract",
                    group="target",
                    required=True,
                    depends_on=["platform"],
                ),
                NodeFieldSchema(
                    name="collection",
                    type="text",
                    label="Save to collection",
                    group="options",
                ),
            ],
            presets=[
                NodePreset(
                    id="extract_posts",
                    display_name="Extract Posts",
                    description="Preset for extracting provider posts.",
                    runtime_step_type="extract",
                    defaults={
                        "type": "extract",
                        "platform": "facebook",
                        "entity": "posts",
                        "content_type": "fb_post",
                    },
                ),
                NodePreset(
                    id="extract_comments",
                    display_name="Extract Comments",
                    description="Preset for extracting comments from the active content.",
                    runtime_step_type="extract",
                    defaults={
                        "type": "extract",
                        "platform": "facebook",
                        "entity": "comments",
                        "content_type": "fb_comment",
                    },
                ),
            ],
        ),
        NodeDefinition(
            node_type="social_open_comments",
            runtime_step_type="social_open_comments",
            schema_version=2,
            capability_id="social.comments.open",
            display_name="Open Comments",
            description="Advanced provider primitive that opens the current content's comments surface.",
            category="Advanced / Provider Primitive",
            legacy={"compound": True, "replacement": "social_find_comment_button -> social_tap_comment_target -> extract"},
        ),
    ]


def build_node_catalog(
    registry: SocialPlatformRegistry | None = None,
) -> dict[str, Any]:
    social_registry = registry or get_social_platform_registry()
    providers = []
    for ext in social_registry.list_platforms():
        providers.append(
            {
                "name": ext.name,
                "version": ext.version,
                "coverage": ext.coverage,
                "enabled_by_default": ext.enabled_by_default,
                "step_types": list(ext.scenario_lib.step_types),
                "entities": list(ext.scenario_lib.entities),
                "capabilities": {
                    capability_id: asdict(support)
                    for capability_id, support in ext.scenario_lib.capabilities.items()
                },
                "capability_schemas": {
                    capability_id: asdict(SOCIAL_CAPABILITY_SCHEMAS[capability_id])
                    for capability_id in ext.scenario_lib.capabilities
                },
                "content_types": [
                    asdict(content_type)
                    for content_type in ext.content_schema.content_types
                ],
            }
        )

    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "execution_model": "deterministic_sequence",
        "nodes": [asdict(definition) for definition in _catalog_definitions()],
        "providers": providers,
    }
