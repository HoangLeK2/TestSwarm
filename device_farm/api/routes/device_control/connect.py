"""QR / ADB connect and scenario schema."""

from __future__ import annotations

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
