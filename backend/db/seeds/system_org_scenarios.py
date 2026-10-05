"""Seed read-only org-scenario templates in the __system org (DF-T-04-005)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import org_scenario as repo
from db.models.enums import OrgScenarioStatus, ScenarioKind
from db.models.organization import Organization
from services.org_scenario_io.constants import SYSTEM_ORG_ID

_NOW = datetime.now(timezone.utc)

_SYSTEM_TEMPLATES: list[dict] = [
    {
        "name": "IG-ProfileFetch",
        "description": "Minimal Instagram profile fetch starter flow.",
        "kind": ScenarioKind.SEQUENCE.value,
        "tags": ["instagram", "template"],
        "body_json": {
            "steps": [
                {
                    "id": "open_ig",
                    "type": "navigation.open_app",
                    "config": {"package": "com.instagram.android"},
                },
                {
                    "id": "wait_profile",
                    "type": "input_wait.wait",
                    "config": {"seconds": 1},
                },
            ]
        },
    },
    {
        "name": "Generic-OpenApp-Wait",
        "description": "Open any package then wait — customize package in clone.",
        "kind": ScenarioKind.SEQUENCE.value,
        "tags": ["starter", "template"],
        "body_json": {
            "steps": [
                {
                    "id": "open_app",
                    "type": "navigation.open_app",
                    "config": {"package": "com.example.app"},
                },
                {
                    "id": "pause",
                    "type": "input_wait.wait",
                    "config": {"seconds": 1},
                },
            ]
        },
    },
    {
        "name": "Graph-Branch-Example",
        "description": "Graph template with conditional branch edges.",
        "kind": ScenarioKind.GRAPH.value,
        "tags": ["graph", "template"],
        "body_json": {
            "nodes": [
                {
                    "id": "start",
                    "type": "navigation.open_app",
                    "config": {"package": "com.example.app"},
                },
                {
                    "id": "success_path",
                    "type": "input_wait.wait",
                    "config": {"seconds": 1},
                },
                {
                    "id": "fallback",
                    "type": "input_wait.wait",
                    "config": {"seconds": 2},
                },
            ],
            "edges": [
                {"source": "start", "target": "success_path", "condition": {"else": True}},
                {"source": "start", "target": "fallback", "condition": {"if_element": "id:popup"}},
            ],
        },
    },
    {
        "name": "Wait-Only-Starter",
        "description": "Smallest runnable sequence for onboarding.",
        "kind": ScenarioKind.SEQUENCE.value,
        "tags": ["starter", "template"],
        "body_json": {
            "steps": [
                {
                    "id": "wait",
                    "type": "input_wait.wait",
                    "config": {"seconds": 1},
                }
            ]
        },
    },
    {
        "name": "Two-Step-Navigation",
        "description": "Open app then tap — common social automation skeleton.",
        "kind": ScenarioKind.SEQUENCE.value,
        "tags": ["navigation", "template"],
        "body_json": {
            "steps": [
                {
                    "id": "open",
                    "type": "navigation.open_app",
                    "config": {"package": "com.example.social"},
                },
                {
                    "id": "tap_cta",
                    "type": "interaction.tap",
                    "config": {"selector": "id:primary_action"},
                },
            ]
        },
    },
]


async def ensure_system_org(db: AsyncSession) -> Organization:
    existing = await db.get(Organization, SYSTEM_ORG_ID)
    if existing is not None:
        return existing
    org = Organization(
        id=SYSTEM_ORG_ID,
        business_name="Device Farm Templates",
        business_email="templates@device-farm.local",
        slug="__system",
        status="active",
        plan="standard",
        created_at=_NOW,
    )
    db.add(org)
    await db.flush()
    return org


async def seed_system_org_templates(db: AsyncSession) -> None:
    from tenancy.context import tenant_context

    await ensure_system_org(db)
    with tenant_context(SYSTEM_ORG_ID):
        for spec in _SYSTEM_TEMPLATES:
            name = spec["name"]
            existing = await repo.find_by_org_and_name_lower(db, SYSTEM_ORG_ID, name.lower())
            if existing is None:
                await repo.create_org_scenario(
                    db,
                    org_id=SYSTEM_ORG_ID,
                    name=name,
                    kind=spec["kind"],
                    description=spec["description"],
                    body_json=spec["body_json"],
                    tags=spec.get("tags"),
                )
                continue
            if existing.status != OrgScenarioStatus.DRAFT.value:
                existing.status = OrgScenarioStatus.DRAFT.value
            if existing.body_json != spec["body_json"]:
                await repo.update_org_scenario(
                    db,
                    existing,
                    description=spec["description"],
                    body_json=spec["body_json"],
                    tags=spec.get("tags"),
                )


async def get_template_by_name(db: AsyncSession, name: str):
    from tenancy.context import tenant_context

    await ensure_system_org(db)
    with tenant_context(SYSTEM_ORG_ID):
        return await repo.find_by_org_and_name_lower(db, SYSTEM_ORG_ID, name.lower())
