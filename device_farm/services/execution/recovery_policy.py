"""Recovery policy parsing and validation for incident scenarios."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


INCIDENT_TYPES = frozenset({
    "app_popup",
    "facebook_popup",
    "profile_page",
    "lost_post_detail",
    "comment_panel_closed",
    "stuck_screen",
    "login_or_checkpoint",
    "unknown",
})

RECOVERY_OUTCOMES = frozenset({
    "retry_step",
    "continue",
    "fail",
    "pause_for_takeover",
    "open_dlq",
})


@dataclass(frozen=True, slots=True)
class RecoverySuccessCheck:
    type: str
    incident_type: str | None = None


@dataclass(frozen=True, slots=True)
class RecoveryRule:
    id: str
    incident_types: tuple[str, ...]
    scope: dict[str, Any] = field(default_factory=dict)
    match: dict[str, Any] = field(default_factory=dict)
    scenario_id: str | None = None
    scenario_name: str | None = None
    max_attempts: int = 1
    timeout_ms: int = 0
    trigger: str = "after_failure"
    success_checks: tuple[RecoverySuccessCheck, ...] = ()
    on_success: str = "retry_step"
    on_failure: str = "fail"


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    enabled: bool = False
    max_total_attempts: int = 0
    max_attempts_per_step: int = 0
    # Wall-clock ceiling for everything recovery does to ONE step. The per-rule
    # attempt counters bound how many playbooks run, not how long they take:
    # each playbook is a full nested scenario whose own taps can each wait out
    # an 8s selector timeout. Six leaf steps averaged 103s of recovery before
    # this existed.
    max_step_recovery_ms: int = 30_000
    rules: tuple[RecoveryRule, ...] = field(default_factory=tuple)


class RecoveryPolicyError(ValueError):
    def __init__(self, message: str, *, code: str = "INVALID_RECOVERY_POLICY") -> None:
        super().__init__(message)
        self.code = code


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _int(value: Any, default: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    return []


def _match(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key in (
        "text_any",
        "text_all",
        "result_any",
        "package_any",
        "activity_any",
        "step_type_any",
        "strategy_any",
    ):
        values = _string_list(raw.get(key))
        if values:
            out[key] = values[:50]
    if raw.get("min_confidence") is not None:
        try:
            out["min_confidence"] = max(0.1, min(1.0, float(raw.get("min_confidence"))))
        except (TypeError, ValueError):
            pass
    return out


def _scope(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ("step_type_any", "step_id_any", "strategy_any"):
        values = _string_list(raw.get(key))
        if values:
            out[key] = values[:50]
    if raw.get("step_index_any") is not None:
        indexes: list[int] = []
        for value in _string_list(raw.get("step_index_any")):
            try:
                indexes.append(max(0, int(value)))
            except ValueError:
                continue
        if indexes:
            out["step_index_any"] = indexes[:50]
    return out


def recovery_scenario_ids_from_policy(raw: Any) -> set[str]:
    """Org-scenario ids referenced by recovery rules (not necessarily campaign scenario_refs)."""
    return {
        rule.scenario_id
        for rule in parse_recovery_policy(raw).rules
        if rule.scenario_id
    }


def parse_recovery_policy(raw: Any) -> RecoveryPolicy:
    if not isinstance(raw, dict) or not raw:
        return RecoveryPolicy()
    enabled = _bool(raw.get("enabled"))
    rules: list[RecoveryRule] = []
    raw_rules = raw.get("rules") if isinstance(raw.get("rules"), list) else []
    for idx, item in enumerate(raw_rules):
        if not isinstance(item, dict):
            continue
        raw_incident_types = item.get("incident_types")
        if not isinstance(raw_incident_types, list):
            raw_incident_types = [item.get("incident_type")]
        incident_types = tuple(
            str(v).strip()
            for v in (raw_incident_types or [])
            if str(v or "").strip()
        ) or ("unknown",)
        checks: list[RecoverySuccessCheck] = []
        for check in item.get("success_checks") or []:
            if not isinstance(check, dict):
                continue
            checks.append(
                RecoverySuccessCheck(
                    type=str(check.get("type") or "").strip(),
                    incident_type=(
                        str(check.get("incident_type")).strip()
                        if check.get("incident_type")
                        else None
                    ),
                )
            )
        success_check = item.get("success_check")
        if isinstance(success_check, dict):
            if _bool(success_check.get("require_post_detail")):
                checks.append(RecoverySuccessCheck(type="post_detail_visible"))
            if _bool(success_check.get("require_comment_panel")):
                checks.append(RecoverySuccessCheck(type="comment_panel_visible"))
        rules.append(
            RecoveryRule(
                id=str(item.get("id") or f"rule-{idx + 1}").strip(),
                incident_types=incident_types,
                scope=_scope(item.get("scope")),
                match=_match(item.get("match")),
                scenario_id=(
                    str(item.get("scenario_id")).strip()
                    if item.get("scenario_id")
                    else None
                ),
                scenario_name=(
                    str(item.get("scenario_name")).strip()
                    if item.get("scenario_name")
                    else None
                ),
                max_attempts=_int(item.get("max_attempts"), 1, min_value=1, max_value=10),
                timeout_ms=_int(
                    item.get("timeout_ms"), 0, min_value=0, max_value=3_600_000
                ),
                trigger=str(item.get("trigger") or "after_failure").strip(),
                success_checks=tuple(checks),
                on_success=str(
                    item.get("on_success") or item.get("outcome") or "retry_step"
                ).strip(),
                on_failure=str(item.get("on_failure") or "fail").strip(),
            )
        )
    return RecoveryPolicy(
        enabled=enabled,
        max_total_attempts=_int(
            raw.get("max_total_attempts"),
            100,
            min_value=0,
            max_value=10_000,
        ),
        max_attempts_per_step=_int(raw.get("max_attempts_per_step"), 2, min_value=0, max_value=20),
        max_step_recovery_ms=_int(
            raw.get("max_step_recovery_ms"),
            30_000,
            min_value=0,  # 0 disables the ceiling
            max_value=600_000,
        ),
        rules=tuple(rules),
    )


def dump_recovery_policy(policy: Any) -> dict[str, Any]:
    if not isinstance(policy, dict):
        return {}
    parsed = parse_recovery_policy(policy)
    if not parsed.enabled and not parsed.rules:
        return {}
    return {
        "enabled": parsed.enabled,
        "max_total_attempts": parsed.max_total_attempts,
        "max_attempts_per_step": parsed.max_attempts_per_step,
        "max_step_recovery_ms": parsed.max_step_recovery_ms,
        "rules": [
            {
                "id": rule.id,
                "incident_type": rule.incident_types[0] if rule.incident_types else "unknown",
                "incident_types": list(rule.incident_types),
                "scope": rule.scope,
                "match": rule.match,
                "scenario_id": rule.scenario_id,
                "scenario_name": rule.scenario_name,
                "max_attempts": rule.max_attempts,
                "timeout_ms": rule.timeout_ms,
                "trigger": rule.trigger,
                "success_check": {
                    "require_post_detail": any(
                        check.type == "post_detail_visible" for check in rule.success_checks
                    ),
                    "require_comment_panel": any(
                        check.type == "comment_panel_visible" for check in rule.success_checks
                    ),
                },
                "success_checks": [
                    {
                        "type": check.type,
                        **({"incident_type": check.incident_type} if check.incident_type else {}),
                    }
                    for check in rule.success_checks
                ],
                "outcome": rule.on_success,
                "on_success": rule.on_success,
                "on_failure": rule.on_failure,
            }
            for rule in parsed.rules
        ],
    }


def validate_recovery_policy_shape(raw: Any) -> RecoveryPolicy:
    policy = parse_recovery_policy(raw)
    if not policy.enabled:
        return policy
    if not policy.rules:
        raise RecoveryPolicyError("Recovery policy enabled but no rules configured")
    seen: set[str] = set()
    for rule in policy.rules:
        if not rule.id:
            raise RecoveryPolicyError("Recovery rule id is required")
        if rule.id in seen:
            raise RecoveryPolicyError(f"Duplicate recovery rule id: {rule.id}")
        seen.add(rule.id)
        unknown = [v for v in rule.incident_types if v not in INCIDENT_TYPES]
        if unknown:
            raise RecoveryPolicyError(
                f"Recovery rule {rule.id}: unsupported incident type {unknown[0]!r}"
            )
        if not (rule.scenario_id or rule.scenario_name):
            raise RecoveryPolicyError(
                f"Recovery rule {rule.id}: scenario_id or scenario_name required"
            )
        if rule.on_success not in RECOVERY_OUTCOMES:
            raise RecoveryPolicyError(f"Recovery rule {rule.id}: invalid on_success")
        if rule.on_failure not in RECOVERY_OUTCOMES:
            raise RecoveryPolicyError(f"Recovery rule {rule.id}: invalid on_failure")
    return policy


async def validate_recovery_policy_references(
    db: AsyncSession,
    *,
    org_id: str,
    raw: Any,
) -> dict[str, Any]:
    policy = validate_recovery_policy_shape(raw)
    if not policy.enabled:
        return dump_recovery_policy(raw)

    scenario_ids = sorted({rule.scenario_id for rule in policy.rules if rule.scenario_id})
    if scenario_ids:
        from db.crud import org_scenario as org_scenario_repo
        from db.models.enums import OrgScenarioStatus

        rows = await org_scenario_repo.get_org_scenario_meta_by_ids(db, org_id, scenario_ids)
        found = {
            row_id: (status, version)
            for row_id, status, version in rows
        }
        for scenario_id in scenario_ids:
            meta = found.get(scenario_id)
            if meta is None or meta[0] == OrgScenarioStatus.ARCHIVED.value:
                raise RecoveryPolicyError(
                    f"Recovery scenario not found: {scenario_id}",
                    code="RECOVERY_SCENARIO_NOT_FOUND",
                )
    return dump_recovery_policy(raw)
