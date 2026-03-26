"""
crawl_jobs.py — API endpoints for crawl job management (scenario-based FB group crawl).

Endpoints:
  POST /api/devices/{serial}/crawl/jobs          — create + run crawl job (blocking)
  POST /api/devices/{serial}/crawl/jobs/enqueue  — enqueue crawl job (background)
  GET  /api/crawl/jobs                           — list all jobs (limit/offset)
  GET  /api/crawl/jobs/{job_id}                  — get job details + post count
  GET  /api/crawl/jobs/{job_id}/posts            — get posts (limit/offset)
  DELETE /api/crawl/jobs/{job_id}                — delete job + all posts
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.config import Config
from runtime.core import DeviceManager, TaskQueue
from runtime.core.task_queue import Task

log = logging.getLogger(__name__)


# ── Request schema ─────────────────────────────────────────────────────────────

class CrawlJobRequest(BaseModel):
    group_id: str = Field(
        "",
        description="Optional group id label for the job (for quick filtering)",
        examples=["123456789"],
    )
    campaign_id: Optional[str] = Field(
        None, description="Optional campaign ID this crawl job belongs to"
    )
    scenario_id: Optional[str] = Field(
        None, description="Optional scenario ID; has higher priority than campaign_id"
    )
    max_posts: int = Field(
        0, ge=0, le=5000,
        description="0 means no post-count cap; crawl until no-new/scroll cap"
    )
    max_scrolls: int = Field(200, ge=1, le=2000)
    auto_append_crawl: bool = Field(
        True,
        description="Auto append default fb_posts crawl loop when scenario has no extract/fb_posts step",
    )
    app: Literal["chrome", "facebook", "facebook_lite"] = "chrome"
    scroll_pause: float = Field(2.5, ge=0.5, le=10.0)
    wait_load: float = Field(4.0, ge=1.0, le=30.0)
    expand_posts: bool = True
    name: str = ""


async def _resolve_scenario_steps(db, body: CrawlJobRequest) -> tuple[list, str]:
    from db import crud as repo

    if body.scenario_id:
        s = await repo.get_scenario(db, body.scenario_id)
        if not s:
            raise ValueError(f"Scenario not found: {body.scenario_id}")
        steps = s.steps or []
        if not steps:
            raise ValueError(f"Scenario has no steps: {body.scenario_id}")
        return steps, f"scenario:{s.id}"

    if body.campaign_id:
        scenarios = await repo.list_scenarios(db, body.campaign_id)
        if not scenarios:
            raise ValueError(f"Campaign has no scenarios: {body.campaign_id}")
        merged_steps: List[dict] = []
        for s in scenarios:
            if s.steps:
                merged_steps.extend(s.steps)
        if not merged_steps:
            raise ValueError(f"Campaign scenarios have no steps: {body.campaign_id}")
        return merged_steps, f"campaign:{body.campaign_id}"

    raise ValueError("Missing scenario source: provide scenario_id or campaign_id")


def _has_fb_posts_extract(steps: list) -> bool:
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("type") == "extract" and step.get("strategy") == "fb_posts":
            return True
        nested = step.get("steps")
        if isinstance(nested, list) and _has_fb_posts_extract(nested):
            return True
    return False


def _build_default_crawl_block(body: CrawlJobRequest) -> dict:
    loop_steps = [
        {
            "type": "extract",
            "strategy": "fb_posts",
            "stop_if_no_new": True,
            "no_new_threshold": 3,
        },
        {"type": "scroll_down", "repeats": 1},
        {"type": "wait", "seconds": body.scroll_pause},
    ]
    if body.max_posts > 0:
        loop_steps.append(
            {"type": "break_if", "condition": {"type": "posts_count_gte", "count": body.max_posts}}
        )
    return {
        "type": "loop",
        "count": body.max_scrolls,
        "steps": loop_steps,
    }


def _finalize_scenario_steps(steps: list, body: CrawlJobRequest) -> tuple[list, bool]:
    if _has_fb_posts_extract(steps):
        return steps, False
    if not body.auto_append_crawl:
        raise ValueError("Scenario has no extract strategy=fb_posts step")
    merged = list(steps)
    merged.append(_build_default_crawl_block(body))
    return merged, True


def _run_crawl_blocking(
    manager: DeviceManager,
    serial: str,
    steps: list,
) -> Dict[str, Any]:
    from tasks.scenario_task import run_scenario_task

    device = manager.get_device(serial)
    if not device:
        return {"error": f"Device {serial} not found"}

    scenario = {"steps": steps}
    ctx: Dict[str, Any] = {}
    result = run_scenario_task(device, scenario, context=ctx)
    posts = result.get("context", {}).get("posts", [])
    result["posts"] = posts
    result["posts_count"] = len(posts)
    return result


def _make_enqueue_crawl_task(
    *,
    steps: list,
    job_id: Optional[str],
    persist_loop: Optional[asyncio.AbstractEventLoop],
):
    from tasks.scenario_task import run_scenario_task

    def _task(device) -> Dict[str, Any]:
        scenario = {"steps": steps}
        ctx: Dict[str, Any] = {}
        result = run_scenario_task(device, scenario, context=ctx)
        posts = result.get("context", {}).get("posts", [])
        result["posts"] = posts
        result["posts_count"] = len(posts)

        if not job_id:
            return result

        async def _persist() -> None:
            from db import crud as repo
            from db.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                async with db.begin():
                    if result.get("success"):
                        saved = await repo.save_crawl_posts(db, job_id, posts)
                        await repo.update_crawl_job(
                            db,
                            job_id,
                            status="done",
                            total_posts=saved,
                            completed_at=datetime.now(timezone.utc),
                        )
                    else:
                        err = result.get("failed_message") or "crawl scenario failed"
                        await repo.update_crawl_job(
                            db,
                            job_id,
                            status="failed",
                            completed_at=datetime.now(timezone.utc),
                            errors=[str(err)],
                        )

        if persist_loop is None:
            return result

        try:
            fut = asyncio.run_coroutine_threadsafe(_persist(), persist_loop)
            fut.result(timeout=30)
        except Exception as exc:  # pragma: no cover - best effort persistence
            log.exception("persist enqueue crawl job failed job_id=%s err=%s", job_id, exc)
        return result

    _task.__name__ = "enqueue_crawl_job"
    return _task


def build_crawl_jobs_router(
    manager: DeviceManager,
    queue: TaskQueue,
    config: Config,
) -> APIRouter:
    router = APIRouter()

    # ── POST /api/devices/{serial}/crawl/jobs — blocking run ──────────────────

    @router.post("/devices/{serial}/crawl/jobs")
    async def api_crawl_job_run(serial: str, body: CrawlJobRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)

        job_id: Optional[str] = None
        resolved_steps: list = []

        if config.database.enabled:
            from db import crud as repo
            from db.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                async with db.begin():
                    try:
                        raw_steps, scenario_source = await _resolve_scenario_steps(db, body)
                        resolved_steps, auto_appended_crawl = _finalize_scenario_steps(raw_steps, body)
                    except ValueError as exc:
                        return JSONResponse({"error": str(exc)}, status_code=400)
                    cfg = {
                        "scenario_source": scenario_source,
                        "auto_appended_crawl": auto_appended_crawl,
                        "max_posts": body.max_posts,
                        "max_scrolls": body.max_scrolls,
                        "scroll_pause": body.scroll_pause,
                        "wait_load": body.wait_load,
                    }
                    job = await repo.create_crawl_job(
                        db,
                        device_serial=serial,
                        campaign_id=body.campaign_id,
                        group_id=body.group_id,
                        app=body.app,
                        config=cfg,
                        scenario_steps=resolved_steps,
                        name=body.name or f"FB Group {body.group_id} - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                    )
                    job_id = job.id
                    await repo.update_crawl_job(db, job_id, status="running")
        else:
            return JSONResponse(
                {"error": "Database not enabled; scenario-based crawl jobs require DB"},
                status_code=503,
            )

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run_crawl_blocking, manager, serial, resolved_steps)

        if "error" in result:
            if job_id and config.database.enabled:
                from db import crud as repo
                from db.database import AsyncSessionLocal
                async with AsyncSessionLocal() as db:
                    async with db.begin():
                        await repo.update_crawl_job(
                            db, job_id,
                            status="failed",
                            completed_at=datetime.now(timezone.utc),
                            errors=[result["error"]],
                        )
            return JSONResponse(result, status_code=400)

        posts = result.get("posts", [])

        if job_id and config.database.enabled:
            from db import crud as repo
            from db.database import AsyncSessionLocal
            async with AsyncSessionLocal() as db:
                async with db.begin():
                    saved = await repo.save_crawl_posts(db, job_id, posts)
                    await repo.update_crawl_job(
                        db, job_id,
                        status="done",
                        total_posts=saved,
                        completed_at=datetime.now(timezone.utc),
                    )
            result["job_id"] = job_id

        return result

    # ── POST /api/devices/{serial}/crawl/jobs/enqueue — background ─────────────

    @router.post("/devices/{serial}/crawl/jobs/enqueue")
    async def api_crawl_job_enqueue(serial: str, body: CrawlJobRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)

        job_id: Optional[str] = None
        if config.database.enabled:
            from db import crud as repo
            from db.database import AsyncSessionLocal

            resolved_steps: list = []
            async with AsyncSessionLocal() as db:
                async with db.begin():
                    try:
                        raw_steps, scenario_source = await _resolve_scenario_steps(db, body)
                        resolved_steps, auto_appended_crawl = _finalize_scenario_steps(raw_steps, body)
                    except ValueError as exc:
                        return JSONResponse({"error": str(exc)}, status_code=400)
                    cfg = {
                        "scenario_source": scenario_source,
                        "auto_appended_crawl": auto_appended_crawl,
                        "max_posts": body.max_posts,
                        "max_scrolls": body.max_scrolls,
                        "scroll_pause": body.scroll_pause,
                        "wait_load": body.wait_load,
                    }
                    job = await repo.create_crawl_job(
                        db,
                        device_serial=serial,
                        campaign_id=body.campaign_id,
                        group_id=body.group_id,
                        app=body.app,
                        config=cfg,
                        scenario_steps=resolved_steps,
                        name=body.name
                        or f"FB Group {body.group_id} - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                    )
                    job_id = job.id
                    await repo.update_crawl_job(db, job_id, status="running")
        else:
            return JSONResponse(
                {"error": "Database not enabled; scenario-based crawl jobs require DB"},
                status_code=503,
            )

        persist_loop = asyncio.get_running_loop()
        task_fn = _make_enqueue_crawl_task(
            steps=resolved_steps,
            job_id=job_id,
            persist_loop=persist_loop,
        )
        task = Task(fn=task_fn, target=serial, priority=5, name=f"crawl:{body.group_id}")
        queue.put(task)

        return {
            "task_id": task.id,
            "serial": serial,
            "group_id": body.group_id,
            "campaign_id": body.campaign_id,
            "job_id": job_id,
            "status": "enqueued",
        }

    # ── GET /api/crawl/jobs ────────────────────────────────────────────────────

    @router.get("/crawl/jobs")
    async def api_list_crawl_jobs(
        campaign_id: Optional[str] = Query(None),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        if not config.database.enabled:
            return JSONResponse({"error": "Database not enabled"}, status_code=503)

        from db import crud as repo
        from db.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            jobs = await repo.list_crawl_jobs(
                db, campaign_id=campaign_id, limit=limit, offset=offset
            )
            return [
                {
                    "id": j.id,
                    "name": j.name,
                    "device_serial": j.device_serial,
                    "campaign_id": j.campaign_id,
                    "group_id": j.group_id,
                    "app": j.app,
                    "status": j.status,
                    "total_posts": j.total_posts,
                    "total_scrolls": j.total_scrolls,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                    "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                }
                for j in jobs
            ]

    # ── GET /api/crawl/jobs/{job_id} ──────────────────────────────────────────

    @router.get("/crawl/jobs/{job_id}")
    async def api_get_crawl_job(job_id: str):
        if not config.database.enabled:
            return JSONResponse({"error": "Database not enabled"}, status_code=503)

        from db import crud as repo
        from db.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            job = await repo.get_crawl_job(db, job_id)
            if not job:
                return JSONResponse({"error": "Job not found"}, status_code=404)
            return {
                "id": job.id,
                "name": job.name,
                "device_serial": job.device_serial,
                "campaign_id": job.campaign_id,
                "group_id": job.group_id,
                "app": job.app,
                "status": job.status,
                "config": job.config,
                "scenario_steps": job.scenario_steps,
                "total_posts": job.total_posts,
                "total_scrolls": job.total_scrolls,
                "errors": job.errors,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "posts_count": len(job.posts),
            }

    # ── GET /api/crawl/jobs/{job_id}/posts ────────────────────────────────────

    @router.get("/crawl/jobs/{job_id}/posts")
    async def api_get_crawl_posts(
        job_id: str,
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        if not config.database.enabled:
            return JSONResponse({"error": "Database not enabled"}, status_code=503)

        from db import crud as repo
        from db.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            posts = await repo.get_crawl_posts(db, job_id, limit=limit, offset=offset)
            return [
                {
                    "id": p.id,
                    "job_id": p.job_id,
                    "author": p.author,
                    "text": p.text,
                    "timestamp_raw": p.timestamp_raw,
                    "reactions": p.reactions,
                    "comments": p.comments,
                    "shares": p.shares,
                    "source_index": p.source_index,
                    "scraped_at": p.scraped_at.isoformat() if p.scraped_at else None,
                }
                for p in posts
            ]

    # ── DELETE /api/crawl/jobs/{job_id} ───────────────────────────────────────

    @router.delete("/crawl/jobs/{job_id}")
    async def api_delete_crawl_job(job_id: str):
        if not config.database.enabled:
            return JSONResponse({"error": "Database not enabled"}, status_code=503)

        from db import crud as repo
        from db.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            async with db.begin():
                deleted = await repo.delete_crawl_job(db, job_id)
            if not deleted:
                return JSONResponse({"error": "Job not found"}, status_code=404)
            return {"deleted": True, "job_id": job_id}

    return router
