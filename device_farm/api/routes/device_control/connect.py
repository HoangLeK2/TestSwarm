"""QR / ADB connect and scenario schema."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import update

from api.schemas.device_control import AdbRegisterRequest
from core.config import Config
from db import crud as repo
from db.database import AsyncSessionLocal
from db.models.device import Device as DeviceModel
from runtime.core import DeviceManager


def build_connect_router(manager: DeviceManager, config: Config) -> APIRouter:
    router = APIRouter()

    @router.get("/connect/info")
    async def api_connect_info():
        return {"registerPath": "/api/connect/register"}

    @router.get("/scenario/schema")
    async def api_scenario_schema():
        from common.scenario_schema import get_scenario_schema

        return get_scenario_schema()

    @router.get("/scenario/device-capabilities/{serial}")
    async def api_scenario_device_capabilities(serial: str):
        from services.scenario_node_preflight import collect_node_capabilities

        device = manager.get_device(serial)
        capabilities = collect_node_capabilities(device, serial=serial)
        return {
            "serial": serial,
            "capabilities": capabilities,
        }

    @router.post("/scenario/preflight/{serial}")
    async def api_scenario_preflight(serial: str, body: dict[str, Any]):
        from services.scenario_node_preflight import (
            collect_node_capabilities,
            preflight_scenario_node_capabilities_for_capabilities,
        )

        scenario = body.get("scenario") if isinstance(body.get("scenario"), dict) else body
        device = manager.get_device(serial)
        capabilities = collect_node_capabilities(device, serial=serial)
        result = preflight_scenario_node_capabilities_for_capabilities(
            capabilities,
            scenario,
            device=device,
        )
        return {
            "serial": serial,
            "capabilities": capabilities,
            "preflight": result.to_dict(),
        }

    @router.post("/connect/register")
    async def api_connect_register(body: AdbRegisterRequest):
        try:
            client = manager.register_adb_device(body.ip, body.port)
            if client is None:
                return JSONResponse(
                    {"ok": False, "error": "ADB connect failed"},
                    status_code=400,
                )

            serial = client.serial

            if config.database.enabled and (body.device_key or "").strip():
                async with AsyncSessionLocal() as db:
                    try:
                        dev = await repo.bind_pending_device(
                            db,
                            body.device_key.strip(),  # type: ignore[arg-type]
                            serial,
                        )
                        if dev is not None:
                            await db.execute(
                                update(DeviceModel)
                                .where(DeviceModel.id == dev.id)
                                .values(adb_ip=body.ip, adb_port=body.port)
                            )
                        await db.commit()
                    except Exception:
                        await db.rollback()

            return {"ok": True, "serial": serial}
        except Exception as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=400,
            )

    return router
