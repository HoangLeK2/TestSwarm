from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api import deps


def _user(role: str = "operator", org_role: str = "owner") -> SimpleNamespace:
    user = SimpleNamespace(id="user-1", role=role, org_id="org-1", is_active=True)
    user.org_role = org_role
    return user


def test_social_ext_contract_exports_stable_interfaces() -> None:
    from services.social_ext.contract import (
        CONTRACT_VERSION,
        PlatformContentTypeSchema,
        PlatformHandler,
        PlatformParser,
        PlatformScenarioLib,
    )

    assert CONTRACT_VERSION == "2.0.0"
    assert PlatformParser
    assert PlatformHandler
    assert PlatformScenarioLib
    assert PlatformContentTypeSchema

    parse_sig = inspect.signature(PlatformParser.parse)
    assert list(parse_sig.parameters) == ["self", "snapshot", "context"]

    execute_sig = inspect.signature(PlatformHandler.execute)
    assert list(execute_sig.parameters) == ["self", "ctx", "step"]


def test_default_social_registry_loads_facebook_and_agent_boot_storage_boundary() -> None:
    from services.social_ext.registry import get_social_platform_registry

    registry = get_social_platform_registry()
    facebook = registry.get_platform("facebook")

    assert facebook is not None
    assert facebook.coverage == "L2 Active"
    assert facebook.enabled_by_default is True
    assert "social_open_comments" in facebook.scenario_lib.step_types
    assert set(facebook.scenario_lib.entities) >= {"posts", "comments"}

    for content_type in facebook.content_schema.content_types:
        assert content_type.storage_owner == "agent-boot"
        assert content_type.raw_data_owner == "agent-boot"
        assert content_type.persisted_in_device_farm is False


def test_social_registry_rejects_parser_without_handler() -> None:
    from services.social_ext.contract import (
        PlatformContentTypeSchema,
        PlatformExtension,
        PlatformScenarioLib,
    )
    from services.social_ext.registry import SocialPlatformRegistry

    class ParserOnly:
        def parse(self, snapshot, context):
            return []

    extension = PlatformExtension(
        name="fake",
        version="1.0.0",
        coverage="Draft",
        parser=ParserOnly(),
        handlers={},
        scenario_lib=PlatformScenarioLib(step_types=[], entities=[]),
        content_schema=PlatformContentTypeSchema(platform="fake", content_types=[]),
    )

    registry = SocialPlatformRegistry(load_defaults=False)

    with pytest.raises(ValueError, match="PLUGIN_HANDLER_REQUIRED"):
        registry.register(extension)


def test_social_registry_feature_flags_default_and_toggle() -> None:
    from services.social_ext.registry import SocialPlatformRegistry

    registry = SocialPlatformRegistry(load_defaults=True)

    flags = registry.flags_for_org("acme")
    assert flags["facebook"]["enabled"] is True
    assert flags["tiktok"]["enabled"] is False
    assert flags["threads"]["enabled"] is False
    assert flags["instagram"]["enabled"] is False

    updated = registry.set_org_platform_enabled("acme", "tiktok", True, note="pilot")
    assert updated["enabled"] is True
    assert updated["note"] == "pilot"
    assert registry.flags_for_org("acme")["tiktok"]["enabled"] is True


def test_social_registry_lifecycle_semver_and_history() -> None:
    from services.social_ext.registry import SocialPlatformRegistry

    registry = SocialPlatformRegistry(load_defaults=True)

    migrated = registry.migrate_platform("facebook", "2.1.0", actor="admin-1")
    assert migrated.version == "2.1.0"

    with pytest.raises(ValueError, match="PLUGIN_INCOMPATIBLE_MAJOR_BUMP"):
        registry.migrate_platform("facebook", "3.0.0", actor="admin-1")

    unloaded = registry.unload_platform("facebook", actor="admin-1")
    assert unloaded["platform"] == "facebook"
    assert registry.get_platform("facebook") is None

    loaded = registry.load_platform("facebook", version="2.0.0", actor="admin-1")
    assert loaded.name == "facebook"
    assert registry.get_platform("facebook") is not None

    events = registry.version_history("facebook")
    assert [event["event"] for event in events] == ["loaded", "migrated", "migrate_rejected", "unloaded", "loaded"]


@pytest.mark.asyncio
async def test_social_ext_routes_discover_platforms_and_flags() -> None:
    from api.routes import social_ext
    from services.social_ext.registry import SocialPlatformRegistry

    app = FastAPI()
    app.include_router(social_ext.router, prefix="/api")
    app.dependency_overrides[deps._get_current_user] = lambda: _user()

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_db] = fake_db
    app.state.social_platform_registry = SocialPlatformRegistry(load_defaults=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        platforms = await client.get("/api/social-ext/platforms")
        steps = await client.get("/api/social-ext/platforms/facebook/steps")
        flags = await client.get("/api/social-ext/orgs/acme/platforms")
        enabled = await client.post(
            "/api/social-ext/orgs/acme/platforms/tiktok/enable",
            json={"note": "pilot"},
        )

    assert platforms.status_code == 200
    assert platforms.json()["platforms"][0]["name"] == "facebook"
    assert platforms.json()["platforms"][0]["storage_owner"] == "agent-boot"

    assert steps.status_code == 200
    body = steps.json()
    assert "social_open_comments" in body["step_types"]
    assert body["extraction_strategies"]["posts"]["storage_owner"] == "agent-boot"

    assert flags.status_code == 200
    assert flags.json()["platforms"]["facebook"]["enabled"] is True
    assert flags.json()["platforms"]["tiktok"]["enabled"] is False

    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["note"] == "pilot"


@pytest.mark.asyncio
async def test_social_ext_lifecycle_routes() -> None:
    from api.routes import social_ext
    from services.social_ext.registry import SocialPlatformRegistry

    app = FastAPI()
    app.include_router(social_ext.router, prefix="/api")
    app.dependency_overrides[deps._get_current_user] = lambda: _user()

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_db] = fake_db
    app.state.social_platform_registry = SocialPlatformRegistry(load_defaults=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        migrated = await client.post(
            "/api/social-ext/platforms/facebook/migrate",
            json={"version": "2.1.0"},
        )
        rejected = await client.post(
            "/api/social-ext/platforms/facebook/migrate",
            json={"version": "3.0.0"},
        )
        unloaded = await client.post("/api/social-ext/platforms/facebook/unload")
        reloaded = await client.post(
            "/api/social-ext/platforms/facebook/load",
            json={"version": "2.0.0"},
        )
        history = await client.get("/api/social-ext/platforms/facebook/version-history")

    assert migrated.status_code == 200
    assert migrated.json()["version"] == "2.1.0"
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "PLUGIN_INCOMPATIBLE_MAJOR_BUMP"
    assert unloaded.status_code == 200
    assert unloaded.json()["event"] == "unloaded"
    assert reloaded.status_code == 200
    assert reloaded.json()["version"] == "2.0.0"
    assert history.status_code == 200
    assert [event["event"] for event in history.json()["events"]] == [
        "loaded",
        "migrated",
        "migrate_rejected",
        "unloaded",
        "loaded",
    ]


@pytest.mark.asyncio
async def test_scenario_templates_can_filter_facebook_platform(monkeypatch) -> None:
    from api.routes import scenarios

    def _view(name: str, tags: list[str]) -> SimpleNamespace:
        return SimpleNamespace(
            id=f"{name}-id",
            organization_id="system",
            name=name,
            description="",
            kind="template",
            status="active",
            scenario_version=1,
            tags=tags,
            created_by=None,
            created_at="2026-05-31T00:00:00",
            updated_at="2026-05-31T00:00:00",
            is_runnable=True,
            last_validation_summary=None,
            last_validated_at=None,
        )

    async def fake_templates(_db):
        return [_view("facebook_template", ["facebook"]), _view("tiktok_template", ["tiktok"])]

    app = FastAPI()
    app.include_router(scenarios.router, prefix="/api")
    app.dependency_overrides[deps._get_current_user] = lambda: _user()

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_db] = fake_db
    class _TemplateRow:
        def __init__(self, name: str, tags: str) -> None:
            self.id = name
            self.name = name
            self.display_name = name
            self.description = ""
            self.category = "general"
            self.steps = [{"id": "s1", "type": "input_wait.wait", "config": {"seconds": 1}}]
            self.nodes = []
            self.edges = []
            self.variables = {}
            self.tags = tags
            self.user_id = None
            self.created_at = None
            self.updated_at = None

    async def fake_template_rows(_db, **kwargs):
        return [
            _TemplateRow("facebook_template", "facebook"),
            _TemplateRow("tiktok_template", "tiktok"),
        ]

    monkeypatch.setattr(scenarios, "list_scenario_template_rows", fake_template_rows)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/scenarios/templates?platform=facebook")

    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == ["facebook_template"]


def test_canonical_facebook_comment_button_schema_and_handler_alias() -> None:
    from api.schemas.scenario import ScenarioModel
    from tasks.scenario.steps import _STEP_HANDLERS

    errors = ScenarioModel.validate_dict({"steps": [{"type": "social_open_comments"}]})

    assert errors == []
    assert _STEP_HANDLERS["social_open_comments"] is _STEP_HANDLERS["social_open_comments"]
