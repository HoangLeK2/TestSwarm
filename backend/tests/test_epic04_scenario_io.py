"""Epic 04 DF-T-04-005: scenario import/export and template library."""
from __future__ import annotations

import json

import pytest
import yaml

pytest_plugins = ["tests.test_epic04_scenario_entity"]

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from db.models.org_scenario import OrgScenario
from db.seeds.scenario_templates import seed_builtin_templates
from services.org_scenario_io.constants import EXPORT_SCHEMA_VERSION
from services.org_scenario_io.serializer import compute_checksum
from tests.test_epic04_scenario_entity import (
    ORG_A,
    ORG_B,
    USER_OWNER,
    USER_OTHER,
    _build_app,
    _seed_orgs,
)


def _sequence_step(step_id: str, step_type: str, **config):
    return {
        "id": step_id,
        "type": step_type,
        "config": config,
    }


async def _seed_system_templates(session_factory):
    async with session_factory() as db:
        await seed_builtin_templates(db)
        await db.commit()


async def _count_org_scenarios(session_factory, org_id: str) -> int:
    async with session_factory() as db:
        result = await db.execute(
            select(func.count()).select_from(OrgScenario).where(OrgScenario.org_id == org_id)
        )
        return int(result.scalar_one())


@pytest.mark.asyncio
async def test_ac1_export_yaml_scrubs_private_fields(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "ExportMe", "kind": "sequence", "tags": ["share"]},
        )
        scenario_id = created.json()["id"]
        await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={
                "steps": [
                    _sequence_step("w", "input_wait.wait", seconds=1),
                ]
            },
        )
        bumped = await client.get(f"/api/scenarios/{scenario_id}")
        version = bumped.json()["scenario_version"]
        resp = await client.get(f"/api/scenarios/{scenario_id}/export?format=yaml")
    assert resp.status_code == 200
    assert "yaml" in resp.headers.get("content-type", "")
    payload = yaml.safe_load(resp.text)
    assert payload["schema_version"] == EXPORT_SCHEMA_VERSION
    assert payload["checksum"].startswith("sha256:")
    assert payload["scenario"]["name"] == "ExportMe"
    assert payload["scenario"]["scenario_version"] == version
    assert "organization_id" not in resp.text
    assert "created_by" not in resp.text
    assert "org_id" not in resp.text


@pytest.mark.asyncio
async def test_ac2_import_valid_yaml_creates_draft_scenario(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory, org_id=ORG_B, user_id=USER_OTHER)
    transport = ASGITransport(app=app)
    payload = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "scenario": {
            "name": "Imported-X",
            "description": "from file",
            "kind": "sequence",
            "tags": ["imported"],
            "scenario_version": 1,
            "body": {
                "steps": [
                    _sequence_step("w", "input_wait.wait", seconds=1),
                ]
            },
        },
    }
    payload["checksum"] = compute_checksum(payload)
    content = yaml.safe_dump(payload).encode("utf-8")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = await _count_org_scenarios(session_factory, ORG_B)
        resp = await client.post(
            "/api/scenarios/import",
            files={"file": ("scenario.yaml", content, "application/x-yaml")},
        )
        after = await _count_org_scenarios(session_factory, ORG_B)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "draft"
    assert data["scenario_version"] == 1
    assert after == before + 1


@pytest.mark.asyncio
async def test_import_edited_file_checksum_mismatch_still_imports_with_warning(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory, org_id=ORG_B, user_id=USER_OTHER)
    transport = ASGITransport(app=app)
    payload = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "scenario": {
            "name": "EditedChecksum",
            "description": "",
            "kind": "sequence",
            "tags": [],
            "scenario_version": 1,
            "body": {"steps": [_sequence_step("w", "input_wait.wait", seconds=1)]},
        },
    }
    payload["checksum"] = compute_checksum(payload)
    payload["scenario"]["description"] = "edited after export"
    content = yaml.safe_dump(payload).encode("utf-8")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/scenarios/import",
            files={"file": ("edited.yaml", content, "application/x-yaml")},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "EditedChecksum"
    assert any("checksum" in w.lower() for w in (data.get("warnings") or []))


@pytest.mark.asyncio
async def test_ac3_import_invalid_graph_rejected_without_row(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory, org_id=ORG_B, user_id=USER_OTHER)
    transport = ASGITransport(app=app)
    payload = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "scenario": {
            "name": "BadGraphImport",
            "description": "",
            "kind": "graph",
            "tags": [],
            "scenario_version": 1,
            "body": {
                "nodes": [
                    _sequence_step("A", "input_wait.wait", seconds=1),
                    _sequence_step("Z", "input_wait.wait", seconds=1),
                ],
                "edges": [],
            },
        },
    }
    payload["checksum"] = compute_checksum(payload)
    content = yaml.safe_dump(payload).encode("utf-8")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = await _count_org_scenarios(session_factory, ORG_B)
        resp = await client.post(
            "/api/scenarios/import",
            files={"file": ("bad.yaml", content, "application/x-yaml")},
        )
        after = await _count_org_scenarios(session_factory, ORG_B)
    assert resp.status_code == 400
    assert resp.json()["detail"]["errors"]
    assert after == before


@pytest.mark.asyncio
async def test_ac4_clone_system_template(session_factory):
    await _seed_orgs(session_factory)
    await _seed_system_templates(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        templates = await client.get("/api/scenarios/templates")
        assert templates.status_code == 200
        template_id = templates.json()[0]["id"]
        template_name = templates.json()[0]["name"]
        before_org_a = await _count_org_scenarios(session_factory, ORG_A)
        clone = await client.post(
            f"/api/scenarios/templates/{template_id}/clone",
            json={"name_override": "MyClone"},
        )
        after_org_a = await _count_org_scenarios(session_factory, ORG_A)
        template_after = await client.get(f"/api/scenario-templates/{template_id}")
    assert clone.status_code == 201
    assert clone.json()["name"] == "MyClone"
    assert clone.json()["status"] == "draft"
    assert after_org_a == before_org_a + 1
    assert template_after.status_code == 200


@pytest.mark.asyncio
async def test_ac5_missing_dependency_reject_and_create_stub(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory, org_id=ORG_B, user_id=USER_OTHER)
    transport = ASGITransport(app=app)
    payload = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "scenario": {
            "name": "S0",
            "description": "",
            "kind": "sequence",
            "tags": [],
            "scenario_version": 1,
            "body": {
                "steps": [
                    {
                        "id": "run_dep",
                        "type": "composition.run_scenario",
                        "config": {"scenario_name": "S_dep"},
                    }
                ]
            },
        },
    }
    payload["checksum"] = compute_checksum(payload)
    content = yaml.safe_dump(payload).encode("utf-8")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        reject = await client.post(
            "/api/scenarios/import",
            files={"file": ("dep.yaml", content, "application/x-yaml")},
        )
        stub = await client.post(
            "/api/scenarios/import?resolve=create_stub",
            files={"file": ("dep.yaml", content, "application/x-yaml")},
        )
    assert reject.status_code == 400
    assert reject.json()["detail"]["code"] == "MISSING_SCENARIO_REFERENCES"
    assert reject.json()["detail"]["missing_scenarios"] == ["S_dep"]
    assert stub.status_code == 201
    assert "S_dep" in stub.json()["created_stub_names"]


@pytest.mark.asyncio
async def test_ac6_schema_version_migration_and_unsupported(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory, org_id=ORG_B, user_id=USER_OTHER)
    transport = ASGITransport(app=app)

    legacy_ok = {
        "schema_version": "1.0",
        "scenario": {
            "name": "Migrated",
            "description": "",
            "kind": "sequence",
            "tags": [],
            "scenario_version": 1,
            "body": {"steps": [_sequence_step("w", "input_wait.wait", seconds=1)]},
        },
    }
    legacy_ok["checksum"] = compute_checksum(legacy_ok)

    too_old = {
        "schema_version": "0.5",
        "scenario": {
            "name": "TooOld",
            "description": "",
            "kind": "sequence",
            "tags": [],
            "scenario_version": 1,
            "body": {"steps": [_sequence_step("w", "input_wait.wait", seconds=1)]},
        },
    }
    too_old["checksum"] = compute_checksum(too_old)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        migrated = await client.post(
            "/api/scenarios/import",
            files={"file": ("legacy.yaml", yaml.safe_dump(legacy_ok).encode(), "application/x-yaml")},
        )
        unsupported = await client.post(
            "/api/scenarios/import",
            files={"file": ("old.yaml", yaml.safe_dump(too_old).encode(), "application/x-yaml")},
        )
    assert migrated.status_code == 201
    assert migrated.json()["warnings"] == ["migrated from 1.0"]
    assert unsupported.status_code == 400
    assert unsupported.json()["detail"]["code"] == "SCHEMA_VERSION_UNSUPPORTED"


@pytest.mark.asyncio
async def test_import_body_into_existing_allows_same_name(session_factory):
    """Import into open scenario must not fail when export name matches an existing row."""
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "SameNameTarget", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]
        await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={"steps": [_sequence_step("old", "input_wait.wait", seconds=1)]},
        )
        exported = await client.get(f"/api/scenarios/{scenario_id}/export?format=yaml")
        before = await _count_org_scenarios(session_factory, ORG_A)
        imported = await client.post(
            f"/api/scenarios/{scenario_id}/import-body",
            files={"file": ("same.yaml", exported.content, "application/x-yaml")},
        )
        after = await _count_org_scenarios(session_factory, ORG_A)
        detail = await client.get(f"/api/scenarios/{scenario_id}")
    assert imported.status_code == 200
    assert imported.json()["scenario_id"] == scenario_id
    assert after == before
    assert detail.json()["body_json"]["steps"][0]["id"] == "old"
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dup_via_create = await client.post(
            "/api/scenarios/import",
            files={"file": ("same.yaml", exported.content, "application/x-yaml")},
        )
    assert dup_via_create.status_code == 409
    assert dup_via_create.json()["detail"]["code"] == "SCENARIO_NAME_DUPLICATE"


@pytest.mark.asyncio
async def test_round_trip_export_import_equivalent_body(session_factory):
    await _seed_orgs(session_factory)
    app_a = _build_app(session_factory, org_id=ORG_A, user_id=USER_OWNER)
    app_b = _build_app(session_factory, org_id=ORG_B, user_id=USER_OTHER)
    transport_a = ASGITransport(app=app_a)
    transport_b = ASGITransport(app=app_b)
    async with AsyncClient(transport=transport_a, base_url="http://test") as client_a:
        created = await client_a.post(
            "/api/scenarios",
            json={"name": "RoundTrip", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]
        body = {
            "steps": [
                _sequence_step("open", "navigation.open_app", package="com.example.app"),
                _sequence_step("wait", "input_wait.wait", seconds=2),
            ],
            "variables": {"KEYWORD": "test"},
        }
        await client_a.post(f"/api/scenarios/{scenario_id}/body", json=body)
        exported = await client_a.get(f"/api/scenarios/{scenario_id}/export?format=json")
    assert exported.status_code == 200
    payload = json.loads(exported.content)
    async with AsyncClient(transport=transport_b, base_url="http://test") as client_b:
        imported = await client_b.post(
            "/api/scenarios/import",
            files={"file": ("roundtrip.json", exported.content, "application/json")},
        )
        detail = await client_b.get(f"/api/scenarios/{imported.json()['scenario_id']}")
    assert imported.status_code == 201
    assert detail.json()["kind"] == "sequence"
    assert detail.json()["body_json"]["steps"][0]["type"] == "navigation.open_app"
    assert detail.json()["body_json"]["variables"]["KEYWORD"] == "test"


@pytest.mark.asyncio
async def test_system_templates_list_requires_read(session_factory):
    await _seed_orgs(session_factory)
    await _seed_system_templates(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/scenarios/templates")
    assert resp.status_code == 200
    assert len(resp.json()) >= 5

@pytest.mark.asyncio
async def test_account_login_effective_creates_system_org_scenario_without_reusing_draft(session_factory):
    await _seed_orgs(session_factory)
    await _seed_system_templates(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        manual = await client.post(
            "/api/scenarios",
            json={
                "name": "Đăng nhập Instagram 1",
                "kind": "sequence",
                "tags": ["login", "instagram"],
                "body_json": {"steps": [{"id": "manual", "type": "input_wait.wait", "seconds": 1}]},
            },
        )
        assert manual.status_code == 201
        manual_id = manual.json()["id"]
        before = await _count_org_scenarios(session_factory, ORG_A)
        ensured = await client.post(
            "/api/scenarios/account-login/effective",
            json={"platform": "instagram"},
        )
        after = await _count_org_scenarios(session_factory, ORG_A)
        again = await client.post(
            "/api/scenarios/account-login/effective",
            json={"platform": "instagram"},
        )
        final = await _count_org_scenarios(session_factory, ORG_A)
        manual_after = await client.get(f"/api/scenarios/{manual_id}")

    assert ensured.status_code == 200
    data = ensured.json()
    assert data["id"] != manual_id
    assert data["status"] == "active"
    assert data["kind"] == "sequence"
    assert data["created_by"] is None
    assert data["is_runnable"] is True
    assert data["body_json"]["steps"]
    assert {
        "login",
        "instagram",
        "login-platform:instagram",
        "account-login",
        "login-override",
        "system-account-login",
    }.issubset(set(data["tags"]))
    assert data["name"].endswith("(Account Login)")
    assert after == before + 1
    assert again.status_code == 200
    assert again.json()["id"] == data["id"]
    assert final == after
    assert manual_after.json()["status"] == "draft"
    assert "system-account-login" not in manual_after.json()["tags"]
