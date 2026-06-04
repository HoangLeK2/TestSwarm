"""Sync bridge from scenario step handlers to Epic 06 extraction services."""
from __future__ import annotations

import asyncio
from typing import Any, Coroutine, TypeVar

from services.content.extraction.models import ExecutionCaptureContext

T = TypeVar("T")


def run_extraction_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run async extraction coroutine from sync scenario step code."""
    from db.database import run_activity_coro

    return run_activity_coro(coro)


def execution_capture_ctx(
    sc: Any,
    step_idx: int,
    kind: str,
    *,
    retention_class: str = "standard",
) -> ExecutionCaptureContext | None:
    """Build capture context when scenario is tied to an execution."""
    exec_id = (
        sc.execution_id
        or sc.scenario.get("execution_id")
        or sc.scenario.get("_execution_id")
        or sc.scenario.get("run_id")
    )
    if not exec_id:
        return None
    org_id = sc.scenario.get("org_id")
    if not org_id:
        campaign_vars = sc.scenario.get("_campaign_vars") or {}
        if isinstance(campaign_vars, dict):
            org_id = campaign_vars.get("__ORG_ID__") or campaign_vars.get("org_id")
    return ExecutionCaptureContext(
        execution_id=str(exec_id),
        step_index=int(step_idx),
        kind=kind,
        org_id=str(org_id) if org_id else None,
        retention_class=retention_class,
    )


def should_persist_artifact(sc: Any, step: dict[str, Any]) -> bool:
    if step.get("persist_artifact") is False:
        return False
    return execution_capture_ctx(sc, 0, "noop") is not None


def map_ocr_languages(raw: Any) -> list[str]:
    if isinstance(raw, list) and raw:
        return [str(x) for x in raw]
    if not raw:
        return ["vi", "en"]
    token = str(raw).strip().lower()
    if token in {"eng", "en"}:
        return ["en"]
    if token in {"vie", "vi"}:
        return ["vi"]
    if "+" in token:
        parts = []
        for piece in token.split("+"):
            parts.extend(map_ocr_languages(piece))
        return parts or ["vi", "en"]
    return ["vi", "en"]


async def capture_screenshot_async(
    capture: Any,
    device: Any,
    *,
    region: dict[str, float] | None,
    persist: bool,
    execution_ctx: ExecutionCaptureContext | None,
) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: capture.capture_screenshot(
            device,
            region=region,
            persist=persist,
            execution_ctx=execution_ctx,
        ),
    )
