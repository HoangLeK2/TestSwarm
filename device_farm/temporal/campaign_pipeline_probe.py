"""Temporal workflow used only by the isolated campaign pipeline benchmark."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="CampaignPipelineProbeWorkflow")
class CampaignPipelineProbeWorkflow:
    """Exercise a campaign execution without issuing a physical device action."""

    @workflow.run
    async def run(self, inp: dict[str, Any]) -> dict[str, Any]:
        delay_ms = max(0, min(60_000, int(inp.get("delay_ms", 250))))
        probe_started = workflow.now()
        probe_result = await workflow.execute_activity(
            "capacity_probe",
            delay_ms,
            start_to_close_timeout=timedelta(seconds=90),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        probe_finished = workflow.now()

        step_result = {
            "index": 0,
            "type": "capacity_probe",
            "ok": True,
            "message": "campaign pipeline probe completed",
            "details": {
                "delay_ms": delay_ms,
                "schedule_to_start_ms": float(
                    probe_result.get("schedule_to_start_ms", 0.0)
                ),
            },
        }
        finalize_result = await workflow.execute_activity(
            "finalize_campaign_probe",
            {
                "campaign_id": str(inp["campaign_id"]),
                "execution_id": str(inp["execution_id"]),
                "run_id": str(inp["execution_id"]),
                "device_serial": str(inp["device_serial"]),
                "org_id": str(inp["org_id"]),
                "success": True,
                "step_results": [step_result],
            },
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return {
            "ok": True,
            "execution_id": str(inp["execution_id"]),
            "schedule_to_start_ms": float(
                probe_result.get("schedule_to_start_ms", 0.0)
            ),
            "probe_ms": max(
                0.0,
                (probe_finished - probe_started).total_seconds() * 1000.0,
            ),
            "finalization_schedule_to_start_ms": float(
                finalize_result.get("schedule_to_start_ms", 0.0)
            ),
            "finalization_duration_ms": float(
                finalize_result.get("duration_ms", 0.0)
            ),
            "finalization_sql_count": int(finalize_result.get("sql_count", 0)),
            "finalization_sql_duration_ms": float(
                finalize_result.get("sql_duration_ms", 0.0)
            ),
            "finalization_sql_by_verb": dict(
                finalize_result.get("sql_by_verb") or {}
            ),
            "finalization_sql_statements": dict(
                finalize_result.get("sql_statements") or {}
            ),
        }
