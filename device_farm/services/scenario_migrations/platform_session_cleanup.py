"""Cleanup user-facing platform session guard nodes from saved scenarios."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Literal

SESSION_GATE_TYPE = "platform_session_gate"
SESSION_READY_VARIABLE = "PLATFORM_SESSION_READY"

CleanupClassification = Literal[
    "login_flow_keep",
    "auth_required_rewrite",
    "public_rewrite",
    "unknown_rewrite",
    "unchanged",
]

_LOGIN_NAME_TOKENS = ("đăng nhập", "dang nhap", "login")
_PUBLIC_NAME_TOKENS = (
    "khám phá page",
    "kham pha page",
    "discovery",
    "crawl bài viết + bình luận fanpage",
    "crawl bai viet + binh luan fanpage",
)
_AUTH_REQUIRED_STEP_TYPES = frozenset(
    {
        "login_if_needed",
        "connection_request",
        "content_interaction",
        "social_connect_visible_people",
        "social_scan_posts_interact",
    }
)
_AUTH_REQUIRED_TAG_TOKENS = frozenset(
    {
        "publish",
        "nurture",
        "interaction",
        "connection",
        "cold-start",
        "app-automation",
    }
)


@dataclass(frozen=True)
class PlatformSessionCleanupResult:
    body: dict[str, Any]
    changed: bool
    classification: CleanupClassification
    removed_gate_count: int = 0
    removed_ready_condition_count: int = 0
    requirement_added: bool = False
    requirement_removed: bool = False


def cleanup_platform_session_body(
    body: dict[str, Any],
    *,
    name: str = "",
    tags: str = "",
) -> PlatformSessionCleanupResult:
    if not isinstance(body, dict):
        return PlatformSessionCleanupResult(
            body={},
            changed=False,
            classification="unchanged",
        )

    next_body = copy.deepcopy(body)
    steps = next_body.get("steps")
    if not isinstance(steps, list):
        return PlatformSessionCleanupResult(
            body=next_body,
            changed=False,
            classification="unchanged",
        )

    all_steps = _flatten_steps(steps)
    if _is_login_flow(name=name, steps=all_steps):
        return PlatformSessionCleanupResult(
            body=next_body,
            changed=False,
            classification="login_flow_keep",
        )

    new_steps, removed_gate_count, removed_ready_count = _rewrite_steps(steps)
    if removed_gate_count or removed_ready_count:
        next_body["steps"] = new_steps

    auth_required = _is_auth_required(name=name, tags=tags, steps=all_steps)
    public_flow = _is_public_flow(name=name, tags=tags)
    requirement_added = False
    requirement_removed = False
    if auth_required:
        requirement_added = _ensure_platform_session_requirement(next_body, "facebook")
        classification: CleanupClassification = "auth_required_rewrite"
    elif public_flow:
        requirement_removed = _remove_platform_session_requirement(next_body, "facebook")
        classification = "public_rewrite"
    else:
        requirement_removed = _remove_platform_session_requirement(next_body, "facebook")
        classification = "unknown_rewrite"

    changed = bool(
        removed_gate_count
        or removed_ready_count
        or requirement_added
        or requirement_removed
    )
    if not changed:
        classification = "unchanged"
    return PlatformSessionCleanupResult(
        body=next_body,
        changed=changed,
        classification=classification,
        removed_gate_count=removed_gate_count,
        removed_ready_condition_count=removed_ready_count,
        requirement_added=requirement_added,
        requirement_removed=requirement_removed,
    )


def cleanup_platform_session_steps(
    steps: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    return _rewrite_steps(copy.deepcopy(steps))


def _rewrite_steps(steps: list[Any]) -> tuple[list[dict[str, Any]], int, int]:
    rewritten: list[dict[str, Any]] = []
    removed_gate_count = 0
    removed_ready_count = 0
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            continue
        step = copy.deepcopy(raw_step)
        if step.get("type") == SESSION_GATE_TYPE:
            removed_gate_count += 1
            continue
        if step.get("type") == "if_variable" and step.get("name") == SESSION_READY_VARIABLE:
            then_steps = step.get("then") if isinstance(step.get("then"), list) else []
            nested, nested_gates, nested_ready = _rewrite_steps(then_steps)
            rewritten.extend(nested)
            removed_ready_count += 1 + nested_ready
            removed_gate_count += nested_gates
            continue
        for key in ("steps", "then", "else"):
            if isinstance(step.get(key), list):
                nested, nested_gates, nested_ready = _rewrite_steps(step[key])
                step[key] = nested
                removed_gate_count += nested_gates
                removed_ready_count += nested_ready
        branches = step.get("branches")
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, dict) and isinstance(branch.get("steps"), list):
                    nested, nested_gates, nested_ready = _rewrite_steps(branch["steps"])
                    branch["steps"] = nested
                    removed_gate_count += nested_gates
                    removed_ready_count += nested_ready
        rewritten.append(step)
    return rewritten, removed_gate_count, removed_ready_count


def _flatten_steps(steps: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        out.append(step)
        for key in ("steps", "then", "else"):
            if isinstance(step.get(key), list):
                out.extend(_flatten_steps(step[key]))
        for branch in step.get("branches") or []:
            if isinstance(branch, dict) and isinstance(branch.get("steps"), list):
                out.extend(_flatten_steps(branch["steps"]))
    return out


def _is_login_flow(*, name: str, steps: list[dict[str, Any]]) -> bool:
    del steps
    normalized = _normalize_text(name)
    return any(token in normalized for token in _LOGIN_NAME_TOKENS)


def _is_public_flow(*, name: str, tags: str) -> bool:
    normalized = _normalize_text(f"{name} {tags}")
    return any(token in normalized for token in _PUBLIC_NAME_TOKENS)


def _is_auth_required(
    *,
    name: str,
    tags: str,
    steps: list[dict[str, Any]],
) -> bool:
    if any(step.get("type") in _AUTH_REQUIRED_STEP_TYPES for step in steps):
        return True
    normalized_tags = {
        token.strip().lower()
        for token in str(tags or "").replace(",", " ").split()
        if token.strip()
    }
    if normalized_tags & _AUTH_REQUIRED_TAG_TOKENS:
        return not _is_public_flow(name=name, tags=tags)
    return False


def _ensure_platform_session_requirement(body: dict[str, Any], platform: str) -> bool:
    requirements = body.setdefault("requirements", {})
    if not isinstance(requirements, dict):
        requirements = {}
        body["requirements"] = requirements
    existing = requirements.get("platform_session")
    desired = {
        "required": True,
        "platform": platform,
        "account_source": "device_primary",
    }
    if existing == desired:
        return False
    requirements["platform_session"] = desired
    return True


def _remove_platform_session_requirement(body: dict[str, Any], platform: str) -> bool:
    requirements = body.get("requirements")
    if not isinstance(requirements, dict):
        return False
    existing = requirements.get("platform_session")
    if not isinstance(existing, dict) or existing.get("platform") != platform:
        return False
    requirements.pop("platform_session", None)
    if not requirements:
        body.pop("requirements", None)
    return True


def _normalize_text(value: str) -> str:
    return str(value or "").strip().lower()
