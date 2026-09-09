"""Authenticated CRUD API mounted at ``/api`` (e.g. ``/api/devices``, ``/api/campaigns``)."""

from fastapi import APIRouter

from api.routes import admin, auth, campaigns, devices, organizations, users, workspace_admin
from api.routes.me import router as me_router
from api.routes.sessions import router as sessions_router
from api.routes.scenario_templates import router as scenario_templates_router
from api.routes.scenarios import router as scenarios_router
from api.routes.device_groups import router as device_groups_router
from api.routes.accounts import router as accounts_router
from api.routes.account_actions import router as account_actions_router
from api.routes.account_discovery import router as account_discovery_router
from api.routes.account_groups import router as account_groups_router
from api.routes.content import router as content_router
from api.routes.artifacts import router as artifacts_router
from api.routes.schedules import router as schedules_router
from api.routes.executions import router as executions_router
from api.routes.relay_agents import router as relay_agents_router
from api.routes.device_reserve import router as device_reserve_router
from api.routes.notifications import router as notifications_router
from api.routes.analytics import router as analytics_router
from api.routes.preview import router as preview_router
from api.routes.social_ext import router as social_ext_router
from api.routes.mcp import router as mcp_router
from api.routes.platform_apps import router as platform_apps_router
from api.routes.external_entities import (
    device_target_groups_router,
    router as external_entities_router,
)
from api.routes.facebook_candidates import router as facebook_candidates_router

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(me_router)
api_router.include_router(sessions_router)
api_router.include_router(admin.router)
api_router.include_router(workspace_admin.router)
api_router.include_router(device_reserve_router)
api_router.include_router(devices.router)
api_router.include_router(users.router)
api_router.include_router(campaigns.router)
api_router.include_router(organizations.router)
api_router.include_router(scenario_templates_router)
api_router.include_router(scenarios_router)
api_router.include_router(device_groups_router)
api_router.include_router(accounts_router)
api_router.include_router(account_actions_router)
api_router.include_router(account_discovery_router)
api_router.include_router(account_groups_router)
api_router.include_router(content_router)
api_router.include_router(artifacts_router)
api_router.include_router(schedules_router)
api_router.include_router(executions_router)
api_router.include_router(relay_agents_router)
api_router.include_router(notifications_router)
api_router.include_router(analytics_router)
api_router.include_router(preview_router)
api_router.include_router(social_ext_router)
api_router.include_router(mcp_router)
api_router.include_router(platform_apps_router)
api_router.include_router(external_entities_router)
api_router.include_router(device_target_groups_router)
api_router.include_router(facebook_candidates_router)
