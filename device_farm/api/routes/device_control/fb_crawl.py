"""
fb_crawl.py — API endpoints for Facebook group post crawling.

Endpoints:
  POST /api/devices/{serial}/fb_crawl
      Run crawl synchronously, return result when done (may take minutes).

  POST /api/devices/{serial}/fb_crawl/enqueue
      Enqueue as a background task, return task_id immediately.
      Poll: GET /api/tasks/{task_id}
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from runtime.core import DeviceManager, TaskQueue
from runtime.core.task_queue import Task

log = logging.getLogger(__name__)


# ── Request schema ─────────────────────────────────────────────────────────────

class FbCrawlRequest(BaseModel):
    group_id: str = Field(
        ...,
        description="Facebook group numeric ID or slug (e.g. '123456789' or 'mygroupslug')",
        examples=["123456789"],
    )
    max_posts: int = Field(
        50,
        ge=1, le=500,
        description="Stop when this many unique posts are collected",
    )
    max_scrolls: int = Field(
        30,
        ge=1, le=200,
        description="Hard scroll limit (safety cap to avoid infinite loop)",
    )
    app: Literal["chrome", "facebook", "facebook_lite"] = Field(
        "chrome",
        description=(
            "App to use: "
            "'chrome' (m.facebook.com) | "
            "'facebook' (com.facebook.katana) | "
            "'facebook_lite' (com.facebook.lite)"
        ),
    )
    scroll_pause: float = Field(
        2.5, ge=0.5, le=10.0,
        description="Seconds to wait after each scroll (for feed to load)",
    )
    wait_load: float = Field(
        4.0, ge=1.0, le=30.0,
        description="Seconds to wait after opening the group URL",
    )
    expand_posts: bool = Field(
        True,
        description="Tap 'See more' buttons to get full post text",
    )
    save_screenshots: bool = Field(
        False,
        description="Include base64-encoded JPEG screenshots at each scroll in the result",
    )


# ── Router builder ─────────────────────────────────────────────────────────────

def build_fb_crawl_router(manager: DeviceManager, queue: TaskQueue) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/devices/{serial}/fb_crawl",
        summary="Crawl Facebook group posts (blocking)",
        description=(
            "Opens the Facebook group on the device and scrolls through the feed, "
            "collecting post data via UIAutomator2 hierarchy XML. "
            "Runs synchronously — the HTTP response is returned when crawling is complete. "
            "For long crawls (>50 posts) consider using the `/fb_crawl/enqueue` variant."
        ),
    )
    async def api_fb_crawl(serial: str, body: FbCrawlRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)

        from tasks.fb_group_crawl import fb_group_crawl_task

        task_fn = fb_group_crawl_task(
            group_id=body.group_id,
            max_posts=body.max_posts,
            max_scrolls=body.max_scrolls,
            app=body.app,
            scroll_pause=body.scroll_pause,
            wait_load=body.wait_load,
            expand_posts=body.expand_posts,
            save_screenshots=body.save_screenshots,
        )

        loop = asyncio.get_running_loop()
        try:
            result: Dict[str, Any] = await loop.run_in_executor(None, task_fn, device)
        except Exception as exc:
            log.exception("fb_crawl error on %s", serial)
            return JSONResponse(
                {"error": str(exc), "success": False, "posts": [], "total": 0},
                status_code=500,
            )

        status_code = 200 if result.get("success") else 500
        return JSONResponse(result, status_code=status_code)

    @router.post(
        "/devices/{serial}/fb_crawl/enqueue",
        summary="Crawl Facebook group posts (background task)",
        description=(
            "Enqueues a Facebook group crawl as a background task. "
            "Returns immediately with a task_id. "
            "Poll GET /api/tasks/{task_id} to check status and retrieve result."
        ),
    )
    async def api_fb_crawl_enqueue(serial: str, body: FbCrawlRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)

        from tasks.fb_group_crawl import fb_group_crawl_task

        task_fn = fb_group_crawl_task(
            group_id=body.group_id,
            max_posts=body.max_posts,
            max_scrolls=body.max_scrolls,
            app=body.app,
            scroll_pause=body.scroll_pause,
            wait_load=body.wait_load,
            expand_posts=body.expand_posts,
            save_screenshots=body.save_screenshots,
        )

        task = Task(fn=task_fn, target=serial, priority=5)
        queue.put(task)
        log.info("fb_crawl enqueued task_id=%s for device %s group=%s", task.id, serial, body.group_id)

        return {
            "task_id":   task.id,
            "serial":    serial,
            "group_id":  body.group_id,
            "status":    "PENDING",
            "poll_url":  f"/api/tasks/{task.id}",
        }

    @router.post(
        "/fb_crawl/fleet",
        summary="Crawl Facebook group posts across all READY devices",
        description=(
            "Enqueues a crawl task on every READY device simultaneously. "
            "Each device crawls independently (parallel). "
            "Returns a list of task_ids to poll individually. "
            "Useful for faster crawling by distributing load across multiple phones."
        ),
    )
    async def api_fb_crawl_fleet(body: FbCrawlRequest, max_devices: int = 0):
        """
        max_devices: max number of devices to use (0 = all READY devices).
        """
        from tasks.fb_group_crawl import fb_group_crawl_task
        from runtime.core.device_client import DeviceState

        ready = [d for d in manager.all_devices() if d.state == DeviceState.READY]
        if not ready:
            return JSONResponse({"error": "No READY devices available"}, status_code=503)
        if max_devices > 0:
            ready = ready[:max_devices]

        tasks: List[Dict[str, Any]] = []
        for device in ready:
            task_fn = fb_group_crawl_task(
                group_id=body.group_id,
                max_posts=body.max_posts,
                max_scrolls=body.max_scrolls,
                app=body.app,
                scroll_pause=body.scroll_pause,
                wait_load=body.wait_load,
                expand_posts=body.expand_posts,
                save_screenshots=body.save_screenshots,
            )
            task = Task(fn=task_fn, target=device.serial, priority=5)
            queue.put(task)
            tasks.append({
                "task_id":  task.id,
                "serial":   device.serial,
                "status":   "PENDING",
                "poll_url": f"/api/tasks/{task.id}",
            })
            log.info("fb_crawl fleet: enqueued task_id=%s device=%s group=%s",
                     task.id, device.serial, body.group_id)

        return {
            "group_id":    body.group_id,
            "device_count": len(tasks),
            "tasks":       tasks,
        }

    return router
