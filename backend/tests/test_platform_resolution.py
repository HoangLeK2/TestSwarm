from __future__ import annotations

from types import SimpleNamespace

from tasks.scenario.steps.platform_resolution import (
    resolve_supported_step_platform,
)


def _ctx(*, scenario=None, ctx=None) -> SimpleNamespace:
    return SimpleNamespace(scenario=scenario or {}, ctx=ctx or {})


def test_explicit_platform_is_traced_and_supported() -> None:
    result: dict[str, object] = {}

    platform = resolve_supported_step_platform(
        _ctx(),
        {"platform": "instagram"},
        "platform_session_gate",
        result,
    )

    assert platform == "instagram"
    assert result["platform_requested"] == "instagram"
    assert result["platform_resolved"] == "instagram"
    assert result["platform_resolution_reason"] == "explicit_step_platform"
    assert result["platform_legacy_default_used"] is False


def test_auto_platform_requires_runtime_context() -> None:
    result: dict[str, object] = {}

    platform = resolve_supported_step_platform(
        _ctx(),
        {"platform": "auto"},
        "platform_session_gate",
        result,
    )

    assert platform is None
    assert result["ok"] is False
    assert result["outcome"] == "platform_required"
    assert result["reason_code"] == "PLATFORM_REQUIRED"
    assert result["platform_resolution_reason"] == "auto_without_platform_context"


def test_auto_platform_resolves_from_scenario_context() -> None:
    result: dict[str, object] = {}

    platform = resolve_supported_step_platform(
        _ctx(scenario={"platform": "threads"}),
        {"platform": "auto"},
        "connection_request",
        result,
    )

    assert platform == "threads"
    assert result["platform_requested"] == "auto"
    assert result["platform_source"] == "scenario.platform"
    assert result["platform_resolution_reason"] == "resolved_from_platform_context"


def test_missing_platform_requires_explicit_context() -> None:
    result: dict[str, object] = {}

    platform = resolve_supported_step_platform(
        _ctx(),
        {},
        "connection_request",
        result,
    )

    assert platform is None
    assert result["platform_requested"] == "missing"
    assert result["platform_resolution_reason"] == "missing_platform_context"
    assert result["outcome"] == "platform_required"
    assert result["reason_code"] == "PLATFORM_REQUIRED"


def test_explicit_platform_is_preserved_without_legacy_fallback() -> None:
    result: dict[str, object] = {}

    platform = resolve_supported_step_platform(
        _ctx(),
        {"platform": "tiktok"},
        "connection_request",
        result,
    )

    assert platform == "tiktok"
    assert result["platform_resolved"] == "tiktok"
    assert result["platform_resolution_reason"] == "explicit_step_platform"
