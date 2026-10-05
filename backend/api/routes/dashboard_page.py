from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from core.config import Config
from runtime.core import DeviceManager


def build_dashboard_router(
    manager: DeviceManager,
    config: Config,
    templates: Jinja2Templates,
    front_end_dist: Optional[str],
) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if front_end_dist and Path(front_end_dist).exists():
            index_path = Path(front_end_dist) / "index.html"
            if index_path.exists():
                return HTMLResponse(content=index_path.read_text())
        devices = [d.status_dict() for d in manager.all_devices()]
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"devices": devices, "config": config},
        )

    return router
