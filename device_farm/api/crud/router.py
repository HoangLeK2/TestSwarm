"""Authenticated CRUD API mounted at ``/api`` (e.g. ``/api/devices``, ``/api/campaigns``)."""

from fastapi import APIRouter

from api.routes import auth, campaigns, devices, organizations, users
from api.routes.scenario_templates import router as scenario_templates_router
from api.routes.device_groups import router as device_groups_router
from api.routes.accounts import router as accounts_router

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(devices.router)
api_router.include_router(users.router)
api_router.include_router(campaigns.router)
api_router.include_router(organizations.router)
api_router.include_router(scenario_templates_router)
api_router.include_router(device_groups_router)
api_router.include_router(accounts_router)
