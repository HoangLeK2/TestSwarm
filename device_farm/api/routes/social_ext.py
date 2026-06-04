from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.deps import CurrentUser, require_permission
from services.social_ext.registry import SocialPlatformRegistry, get_social_platform_registry

router = APIRouter(prefix="/social-ext", tags=["social-ext"])


class PlatformFlagBody(BaseModel):
    note: str = ""


class PlatformLifecycleBody(BaseModel):
    version: str | None = None
    note: str = ""


def _registry(request: Request) -> SocialPlatformRegistry:
    registry = getattr(request.app.state, "social_platform_registry", None)
    if isinstance(registry, SocialPlatformRegistry):
        return registry
    return get_social_platform_registry()


def _platform_summary(ext) -> dict[str, Any]:
    strategies = ext.scenario_lib.strategies
    return {
        "name": ext.name,
        "version": ext.version,
        "coverage": ext.coverage,
        "lifecycle": ext.lifecycle,
        "enabled_by_default": ext.enabled_by_default,
        "step_type_count": len(ext.scenario_lib.step_types),
        "strategy_count": len(ext.scenario_lib.extraction_strategies),
        "storage_owner": "agent-boot",
        "raw_data_owner": "agent-boot",
        "parser_module": ext.content_schema.parser_module,
        "strategies": {name: asdict(schema) for name, schema in strategies.items()},
    }


@router.get(
    "/platforms",
    dependencies=[Depends(require_permission("social-ext", "read"))],
)
async def list_social_platforms(request: Request, _: CurrentUser):
    registry = _registry(request)
    return {"platforms": [_platform_summary(ext) for ext in registry.list_platforms()]}


@router.get(
    "/platforms/{platform}/steps",
    dependencies=[Depends(require_permission("social-ext", "read"))],
)
async def get_social_platform_steps(platform: str, request: Request, _: CurrentUser):
    registry = _registry(request)
    try:
        return registry.steps_for_platform(platform)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "PLATFORM_NOT_FOUND"}) from exc


@router.post(
    "/platforms/{platform}/load",
    dependencies=[Depends(require_permission("social-ext", "manage"))],
)
async def load_social_platform(
    platform: str,
    body: PlatformLifecycleBody,
    request: Request,
    user: CurrentUser,
):
    registry = _registry(request)
    try:
        extension = registry.load_platform(
            platform,
            version=body.version,
            actor=str(getattr(user, "id", "unknown")),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "PLATFORM_NOT_FOUND"}) from exc
    return _platform_summary(extension)


@router.post(
    "/platforms/{platform}/unload",
    dependencies=[Depends(require_permission("social-ext", "manage"))],
)
async def unload_social_platform(platform: str, request: Request, user: CurrentUser):
    registry = _registry(request)
    try:
        return registry.unload_platform(platform, actor=str(getattr(user, "id", "unknown")))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "PLATFORM_NOT_FOUND"}) from exc


@router.post(
    "/platforms/{platform}/migrate",
    dependencies=[Depends(require_permission("social-ext", "manage"))],
)
async def migrate_social_platform(
    platform: str,
    body: PlatformLifecycleBody,
    request: Request,
    user: CurrentUser,
):
    registry = _registry(request)
    try:
        extension = registry.migrate_platform(
            platform,
            body.version or "",
            actor=str(getattr(user, "id", "unknown")),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "PLATFORM_NOT_FOUND"}) from exc
    except ValueError as exc:
        code = str(exc)
        if code == "PLUGIN_INCOMPATIBLE_MAJOR_BUMP":
            raise HTTPException(status_code=409, detail={"code": code}) from exc
        raise HTTPException(status_code=422, detail={"code": "PLUGIN_INVALID_VERSION"}) from exc
    return _platform_summary(extension)


@router.get(
    "/platforms/{platform}/version-history",
    dependencies=[Depends(require_permission("social-ext", "read"))],
)
async def get_social_platform_version_history(platform: str, request: Request, _: CurrentUser):
    registry = _registry(request)
    if registry.get_platform(platform) is None and not registry.version_history(platform):
        raise HTTPException(status_code=404, detail={"code": "PLATFORM_NOT_FOUND"})
    return {"platform": platform, "events": registry.version_history(platform)}


@router.get(
    "/orgs/{org_id}/platforms",
    dependencies=[Depends(require_permission("social-ext", "read"))],
)
async def list_org_social_platform_flags(org_id: str, request: Request, _: CurrentUser):
    registry = _registry(request)
    return {"org_id": org_id, "platforms": registry.flags_for_org(org_id)}


@router.post(
    "/orgs/{org_id}/platforms/{platform}/enable",
    dependencies=[Depends(require_permission("social-ext", "manage"))],
)
async def enable_org_social_platform(
    org_id: str,
    platform: str,
    body: PlatformFlagBody,
    request: Request,
    _: CurrentUser,
):
    registry = _registry(request)
    try:
        return registry.set_org_platform_enabled(org_id, platform, True, note=body.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "PLATFORM_NOT_FOUND"}) from exc


@router.post(
    "/orgs/{org_id}/platforms/{platform}/disable",
    dependencies=[Depends(require_permission("social-ext", "manage"))],
)
async def disable_org_social_platform(
    org_id: str,
    platform: str,
    body: PlatformFlagBody,
    request: Request,
    _: CurrentUser,
):
    registry = _registry(request)
    try:
        return registry.set_org_platform_enabled(org_id, platform, False, note=body.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "PLATFORM_NOT_FOUND"}) from exc
