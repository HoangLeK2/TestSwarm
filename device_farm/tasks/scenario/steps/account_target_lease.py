"""Scenario step for leasing the next unused account action target."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tasks.scenario.steps import register_step

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext


@register_step("lease_source_target")
def handle_lease_source_target(
    sc: ScenarioContext,
    step: dict[str, Any],
    idx: int,
    result: dict[str, Any],
) -> None:
    from services.account_actions import resolve_action_identity
    from services.account_target_runtime import lease_account_target_blocking

    try:
        identity = resolve_action_identity(
            step=step,
            scenario=sc.scenario,
            variables=sc.ctx.get("vars", {}),
            execution_id=sc.execution_id,
            device_serial=sc.serial,
        )
        lease = lease_account_target_blocking(
            identity=identity,
            platform=str(step.get("platform") or "facebook"),
            entity_type=str(step.get("entity_type") or "post"),
            action_type=str(step.get("action_type") or "content_interaction"),
            action=str(step.get("action") or "like"),
            statuses=step.get("statuses") or ("approved", "active"),
            keywords=step.get("keywords") or step.get("search"),
        )
    except (LookupError, RuntimeError, ValueError) as exc:
        result.update(
            {
                "ok": False,
                "outcome": "target_lease_failed",
                "message": f"lease_source_target: {exc}",
            }
        )
        return

    variables = {
        "TARGET_AVAILABLE": bool(lease["available"]),
        "TARGET_ACTION_ID": lease.get("account_action_id") or "",
        "TARGET_ENTITY_ID": lease.get("external_entity_id") or "",
        "TARGET_EXTERNAL_ID": lease.get("external_id") or "",
        "TARGET_NAME": lease.get("display_name") or "",
        "TARGET_SEARCH_TEXT": lease.get("target_search_text")
        or lease.get("display_name")
        or "",
        "TARGET_URL": lease.get("canonical_url") or "",
    }
    for name, value in variables.items():
        sc.var_ctx.set(name, value)
        sc.ctx.setdefault("vars", {})[name] = value
    result.update(lease)
    result["message"] = (
        "lease_source_target: target leased"
        if lease["available"]
        else "lease_source_target: no unused target matches this account and keyword"
    )
