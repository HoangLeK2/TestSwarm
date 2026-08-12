"""Scenario step that leases one account-scoped connection candidate."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tasks.scenario.steps import register_step

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext


@register_step("lease_connection_candidate")
def handle_lease_connection_candidate(
    sc: "ScenarioContext",
    step: dict[str, Any],
    idx: int,
    result: dict[str, Any],
) -> None:
    platform = str(step.get("platform") or "facebook").strip().casefold()
    if platform != "facebook":
        result.update(
            {
                "ok": False,
                "outcome": "unsupported_platform",
                "message": f"lease_connection_candidate: unsupported {platform!r}",
            }
        )
        return

    from services.account_actions import resolve_action_identity
    from services.facebook_candidate_runtime import lease_connection_candidate

    try:
        identity = resolve_action_identity(
            step=step,
            scenario=sc.scenario,
            variables=sc.ctx.get("vars", {}),
            execution_id=sc.execution_id,
        )
        lease = lease_connection_candidate(
            identity=identity, execution_id=sc.execution_id
        )
    except (LookupError, RuntimeError, ValueError) as exc:
        result.update(
            {
                "ok": False,
                "outcome": "candidate_lease_failed",
                "message": f"lease_connection_candidate: {exc}",
            }
        )
        return

    variables = {
        "CANDIDATE_AVAILABLE": bool(lease["available"]),
        "CANDIDATE_ID": lease.get("candidate_id") or "",
        "CANDIDATE_ENTITY_ID": lease.get("external_entity_id") or "",
        "CANDIDATE_EXTERNAL_ID": lease.get("external_id") or "",
        "CANDIDATE_NAME": lease.get("display_name") or "",
        "CANDIDATE_URL": lease.get("canonical_url") or "",
        "CANDIDATE_LEASE_TOKEN": lease.get("lease_token") or "",
        "TARGET_ENTITY_ID": lease.get("external_entity_id") or "",
        "TARGET_EXTERNAL_ID": lease.get("external_id") or "",
        "TARGET_NAME": lease.get("display_name") or "",
        "TARGET_URL": lease.get("canonical_url") or "",
    }
    for name, value in variables.items():
        sc.var_ctx.set(name, value)
        sc.ctx.setdefault("vars", {})[name] = value
    result.update(lease)
    if lease["available"]:
        result["message"] = "lease_connection_candidate: candidate leased"
    elif lease.get("discovery") is not None:
        result["message"] = (
            "lease_connection_candidate: discovery completed; "
            "no eligible candidate"
        )
    else:
        result["message"] = (
            "lease_connection_candidate: no candidate; discovery requested"
        )
