"""Rewrite stored scenarios to the platform-neutral node vocabulary (migration 111).

Pure functions, no DB access — the same rewrite runs from the migration, from the
seed check, and from tests. Every function mutates in place and returns whether
anything changed, so callers can skip untouched rows.

All rewrites are idempotent: running them twice is a no-op.
"""

from __future__ import annotations

from typing import Any

# Old step type → new step type.
STEP_TYPE_RENAMES: dict[str, str] = {
    "facebook_session_gate": "platform_session_gate",
    "fb_connect_visible_people": "social_connect_visible_people",
    "fb_find_comment_button": "social_find_comment_button",
    "fb_tap_comment_target": "social_tap_comment_target",
    "fb_apply_comment_filter": "social_apply_comment_filter",
    "fb_tap_comment_button": "social_open_comments",
    "tap_fb_comment_button": "social_open_comments",
    "fb_scan_posts_interact": "social_scan_posts_interact",
    "fb_open_author_from_post_match": "social_open_author_from_post_match",
    "fb_open_commenter_from_post_match": "social_open_commenter_from_post_match",
}

# Old step type → (new step type, extra fields identifying the variant).
STEP_TYPE_MERGES: dict[str, tuple[str, dict[str, Any]]] = {
    "fb_select_people_profile": ("social_select_target", {"target_type": "person"}),
    "fb_select_post_target": ("social_select_target", {"target_type": "post"}),
}

# Step types that gain an explicit platform when migrated. These only ever ran
# against Facebook, so stamping it preserves behaviour exactly.
_PLATFORM_STAMPED_TYPES = frozenset(
    set(STEP_TYPE_RENAMES.values()) | {"social_select_target"}
)

# extract: old strategy → (entity, platform).
EXTRACT_STRATEGY_MAP: dict[str, tuple[str, str]] = {
    "fb_posts": ("posts", "facebook"),
    "fb_comments": ("comments", "facebook"),
    "fb_groups": ("groups", "facebook"),
    "fb_pages": ("pages", "facebook"),
    "ig_posts": ("posts", "instagram"),
    "ig_comments": ("comments", "instagram"),
    "tiktok_posts": ("posts", "tiktok"),
    "tiktok_comments": ("comments", "tiktok"),
    "linkedin_posts": ("posts", "linkedin"),
    "linkedin_comments": ("comments", "linkedin"),
    "threads_posts": ("posts", "threads"),
    "threads_comments": ("comments", "threads"),
    "auto_posts": ("posts", "auto"),
    "auto_comments": ("comments", "auto"),
    "text_nodes": ("text_nodes", "ui"),
}

# Runtime context variables renamed alongside the nodes.
VARIABLE_RENAMES: dict[str, str] = {
    "FACEBOOK_SESSION_READY": "PLATFORM_SESSION_READY",
}

# Context keys a scenario can reference by name (e.g. parent_post_id_var).
CTX_KEY_RENAMES: dict[str, str] = {
    "_fb_comment_parent_pid": "_comment_parent_pid",
    "_fb_comment_session": "_comment_session",
    "_fb_comment_target": "_comment_target",
    "_fb_comment_target_missing": "_pending_scroll_target",
    "_fb_posts_dedupe_field": "_posts_dedupe_field",
}

# Fields whose *value* is a variable/context key name rather than data.
_VAR_NAME_FIELDS = (
    "name",
    "save_as",
    "save_success_as",
    "data_var",
    "extract_var",
    "parent_id_var",
    "save_parent_id_var",
    "parent_post_id_var",
    "loop_var",
    "output_prefix",
)

_NESTED_LIST_KEYS = ("steps", "then", "else", "else_steps")


def _rewrite_var_name(value: Any) -> tuple[Any, bool]:
    if not isinstance(value, str):
        return value, False
    renamed = VARIABLE_RENAMES.get(value) or CTX_KEY_RENAMES.get(value)
    if renamed:
        return renamed, True
    return value, False


def _rewrite_interpolations(value: Any) -> tuple[Any, bool]:
    """Rewrite ``${OLD_VAR}`` references embedded anywhere in a string."""
    if not isinstance(value, str) or "${" not in value:
        return value, False
    changed = False
    for old, new in VARIABLE_RENAMES.items():
        token = "${" + old + "}"
        if token in value:
            value = value.replace(token, "${" + new + "}")
            changed = True
    return value, changed


def _migrate_extract_fields(step: dict[str, Any]) -> bool:
    """Convert ``strategy`` into ``entity`` + ``platform``."""
    if "strategy" not in step:
        return False
    strategy = str(step.get("strategy") or "")
    mapped = EXTRACT_STRATEGY_MAP.get(strategy)
    if mapped is None:
        return False
    entity, platform = mapped
    step.pop("strategy", None)
    step["entity"] = entity
    step.setdefault("platform", platform)
    version = step.pop("strategy_version", None)
    if version is not None and "entity_version" not in step:
        # "fb_comments:v1" → "comments:v1"; keep any custom suffix.
        suffix = str(version).split(":", 1)[1] if ":" in str(version) else "v1"
        step["entity_version"] = f"{entity}:{suffix}"
    return True


def _migrate_one(step: dict[str, Any]) -> bool:
    changed = False
    step_type = str(step.get("type") or "")

    merged = STEP_TYPE_MERGES.get(step_type)
    if merged is not None:
        new_type, extra = merged
        step["type"] = new_type
        for key, val in extra.items():
            step.setdefault(key, val)
        step_type = new_type
        changed = True
    elif step_type in STEP_TYPE_RENAMES:
        step["type"] = STEP_TYPE_RENAMES[step_type]
        step_type = step["type"]
        changed = True

    if step_type in _PLATFORM_STAMPED_TYPES and not step.get("platform"):
        step["platform"] = "facebook"
        changed = True

    if step_type == "extract" and _migrate_extract_fields(step):
        changed = True

    for field in _VAR_NAME_FIELDS:
        if field in step:
            new_value, did = _rewrite_var_name(step[field])
            if did:
                step[field] = new_value
                changed = True

    for key, value in list(step.items()):
        new_value, did = _rewrite_interpolations(value)
        if did:
            step[key] = new_value
            changed = True

    return changed


def migrate_step_types(steps: Any) -> bool:
    """Rewrite a steps[] tree in place, recursing into nested branches."""
    if not isinstance(steps, list):
        return False
    changed = False
    for step in steps:
        if not isinstance(step, dict):
            continue
        if _migrate_one(step):
            changed = True
        for key in _NESTED_LIST_KEYS:
            if migrate_step_types(step.get(key)):
                changed = True
        branches = step.get("branches")
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, dict) and migrate_step_types(branch.get("steps")):
                    changed = True
    return changed


def migrate_graph_nodes(nodes: Any) -> bool:
    """Rewrite graph nodes in place.

    A node keeps its step fields under ``config`` and its step type under
    ``type``, so both need rewriting. Migration 078 only touched ``steps`` and
    left these columns stale — do not repeat that.
    """
    if not isinstance(nodes, list):
        return False
    changed = False
    for node in nodes:
        if not isinstance(node, dict):
            continue
        config = node.get("config")
        # Rewrite type + config as if it were one flat step, then split back.
        flat: dict[str, Any] = {"type": node.get("type")}
        if isinstance(config, dict):
            flat.update(config)
        if _migrate_one(flat):
            node["type"] = flat.pop("type", node.get("type"))
            if isinstance(config, dict):
                config.clear()
                config.update(flat)
            else:
                node["config"] = flat
            changed = True
    return changed


def migrate_scenario_blob(blob: Any) -> bool:
    """Rewrite a whole scenario dict (steps + nodes + nested scenarios)."""
    if not isinstance(blob, dict):
        return False
    changed = False
    if migrate_step_types(blob.get("steps")):
        changed = True
    if migrate_graph_nodes(blob.get("nodes")):
        changed = True
    for key in ("scenarios", "flows"):
        nested = blob.get(key)
        if isinstance(nested, list):
            for item in nested:
                if migrate_scenario_blob(item):
                    changed = True
    variables = blob.get("variables")
    if isinstance(variables, dict):
        for old, new in VARIABLE_RENAMES.items():
            if old in variables and new not in variables:
                variables[new] = variables.pop(old)
                changed = True
    return changed
