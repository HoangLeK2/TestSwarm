from __future__ import annotations

import asyncio
from typing import Any

from temporalio import activity


class RelayOnboardingActivities:
    @activity.defn
    async def prepare_relay_onboarding_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        from services import relay_onboarding

        job_id = str(payload.get("job_id") or "").strip()
        if not job_id:
            raise ValueError("job_id is required")
        activity.heartbeat({"job_id": job_id, "stage": "prepare"})
        return await relay_onboarding.prepare_relay_batch_job(job_id)

    @activity.defn
    async def run_relay_onboarding_item(self, payload: dict[str, Any]) -> None:
        from services import relay_onboarding

        job_id = str(payload.get("job_id") or "").strip()
        item_id = str(payload.get("item_id") or "").strip()
        if not job_id or not item_id:
            raise ValueError("job_id and item_id are required")

        stop = asyncio.Event()

        async def _heartbeat_loop() -> None:
            while not stop.is_set():
                activity.heartbeat({"job_id": job_id, "item_id": item_id, "stage": "running"})
                try:
                    await asyncio.wait_for(stop.wait(), timeout=10)
                except asyncio.TimeoutError:
                    pass

        heartbeat_task = asyncio.create_task(_heartbeat_loop())
        try:
            claim_options = _claim_options_from_payload(payload, relay_onboarding)
            await relay_onboarding.run_relay_batch_item(job_id, item_id, claim_connect=claim_options)
        finally:
            stop.set()
            await heartbeat_task
            activity.heartbeat({"job_id": job_id, "item_id": item_id, "stage": "done"})

    @activity.defn
    async def finish_relay_onboarding_job(self, job_id: str) -> None:
        from services import relay_onboarding

        job_id = str(job_id or "").strip()
        if not job_id:
            raise ValueError("job_id is required")
        activity.heartbeat({"job_id": job_id, "stage": "finish"})
        await relay_onboarding.finish_relay_batch_job(job_id)


def _claim_options_from_payload(payload: dict[str, Any], relay_onboarding):
    claim_payload = payload.get("claim_connect")
    if isinstance(claim_payload, dict):
        return relay_onboarding.ClaimConnectOptions(
            connect=bool(claim_payload.get("connect", True)),
            ws_base_url=str(claim_payload.get("ws_base_url") or ""),
        )
    return None
