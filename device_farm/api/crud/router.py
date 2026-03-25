"""Authenticated CRUD API mounted at ``/api`` (e.g. ``/api/devices``, ``/api/campaigns``)."""

from fastapi import APIRouter

from api.routes import auth, campaigns, devices, organizations, users

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(devices.router)
api_router.include_router(users.router)
api_router.include_router(campaigns.router)
api_router.include_router(organizations.router)
