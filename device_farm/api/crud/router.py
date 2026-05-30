"""Authenticated CRUD API mounted at ``/api`` (e.g. ``/api/devices``, ``/api/campaigns``)."""

from fastapi import APIRouter

from api.routes import auth, campaigns, devices, organizations, users
from api.routes.me import router as me_router
from api.routes.scenario_templates import router as scenario_templates_router
from api.routes.device_groups import router as device_groups_router
from api.routes.accounts import router as accounts_router
from api.routes.account_groups import router as account_groups_router
from api.routes.content import router as content_router
from api.routes.schedules import router as schedules_router
from api.routes.executions import router as executions_router
from api.routes.relay_agents import router as relay_agents_router
from api.routes.notifications import router as notifications_router
from api.routes.analytics import router as analytics_router

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(me_router)
api_router.include_router(devices.router)
api_router.include_router(users.router)
api_router.include_router(campaigns.router)
api_router.include_router(organizations.router)
api_router.include_router(scenario_templates_router)
api_router.include_router(device_groups_router)
api_router.include_router(accounts_router)
api_router.include_router(account_groups_router)
api_router.include_router(content_router)
api_router.include_router(schedules_router)
api_router.include_router(executions_router)
api_router.include_router(relay_agents_router)
api_router.include_router(notifications_router)
api_router.include_router(analytics_router)
