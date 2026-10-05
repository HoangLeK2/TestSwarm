from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from api.deps import _get_current_user
from db.models.ai_device_lab_fleet import DeviceHygieneAudit, DeviceHygieneState
from db.models.device import Device
from tenancy.context import set_current_org_id, tenant_context
from tests.tenancy_test_support import (
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    build_tenancy_api_app,
    seed_two_org_fixture,
)


def _owner_override(user_id: str, org_id: str):
    async def _override():
        set_current_org_id(org_id)
        return SimpleNamespace(
            id=user_id,
            email=f"{user_id}@example.com",
            name=user_id,
            role="owner",
            org_role="owner",
            is_active=True,
            org_id=org_id,
        )

    return _override


@pytest.mark.asyncio
async def test_owner_records_emulator_hygiene_and_cross_org_device_stays_hidden(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            db.add(
                Device(
                    id="hygiene-emulator-a",
                    org_id=ORG_A,
                    user_id=USER_A,
                    serial="emulator-5580",
                    name="ADL emulator A",
                )
            )
            await db.commit()
    with tenant_context(ORG_B):
        async with tenancy_session_factory() as db:
            db.add(
                Device(
                    id="hygiene-emulator-b",
                    org_id=ORG_B,
                    user_id=USER_B,
                    serial="emulator-5680",
                    name="ADL emulator B",
                )
            )
            await db.commit()

    app = build_tenancy_api_app(tenancy_session_factory)
    app.dependency_overrides[_get_current_user] = _owner_override(USER_A, ORG_A)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        clean = await client.post(
            "/api/ai-device-lab/devices/hygiene-emulator-a/hygiene-results",
            json={
                "target_type": "emulator",
                "protocol_version": "emulator-hygiene-v1",
                "reset_succeeded": True,
                "readback_clean": True,
                "evidence_ref": "evidence://adl-19a/emulator-5580/clean-readback",
                "active_run": False,
            },
        )
        assert clean.status_code == 200, clean.text
        assert clean.json() == {
            "device_id": "hygiene-emulator-a",
            "target_type": "emulator",
            "state": "verified_clean",
            "protocol_version": "emulator-hygiene-v1",
            "reason_code": "CLEAN_READBACK_VERIFIED",
            "verification_evidence_ref": "evidence://adl-19a/emulator-5580/clean-readback",
        }

        hidden = await client.post(
            "/api/ai-device-lab/devices/hygiene-emulator-b/hygiene-results",
            json={
                "target_type": "emulator",
                "protocol_version": "emulator-hygiene-v1",
                "reset_succeeded": True,
                "readback_clean": True,
                "evidence_ref": "evidence://must-not-write",
                "active_run": False,
            },
        )
        assert hidden.status_code == 404, hidden.text

    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            state = await db.get(DeviceHygieneState, "hygiene-emulator-a")
            audits = list(
                (
                    await db.execute(
                        select(DeviceHygieneAudit).where(
                            DeviceHygieneAudit.device_id == "hygiene-emulator-a"
                        )
                    )
                )
                .scalars()
                .all()
            )

    assert state is not None and state.state == "verified_clean"
    assert len(audits) == 1
    assert audits[0].details["target_type"] == "emulator"


@pytest.mark.asyncio
async def test_hygiene_result_fails_closed_for_dirty_readback_and_active_run(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            db.add(
                Device(
                    id="hygiene-emulator-fail-closed",
                    org_id=ORG_A,
                    user_id=USER_A,
                    serial="emulator-5582",
                    name="ADL emulator fail closed",
                )
            )
            await db.commit()

    app = build_tenancy_api_app(tenancy_session_factory)
    app.dependency_overrides[_get_current_user] = _owner_override(USER_A, ORG_A)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        dirty = await client.post(
            "/api/ai-device-lab/devices/hygiene-emulator-fail-closed/hygiene-results",
            json={
                "target_type": "emulator",
                "protocol_version": "emulator-hygiene-v1",
                "reset_succeeded": True,
                "readback_clean": False,
                "evidence_ref": "evidence://adl-19a/dirty-readback",
                "active_run": False,
            },
        )
        assert dirty.status_code == 200, dirty.text
        assert dirty.json()["state"] == "quarantined"
        assert dirty.json()["reason_code"] == "CLEAN_READBACK_NOT_PROVEN"
        assert dirty.json()["verification_evidence_ref"] is None

        draining = await client.post(
            "/api/ai-device-lab/devices/hygiene-emulator-fail-closed/hygiene-results",
            json={
                "target_type": "emulator",
                "protocol_version": "emulator-hygiene-v1",
                "reset_succeeded": True,
                "readback_clean": True,
                "evidence_ref": "evidence://adl-19a/clean-but-active",
                "active_run": True,
            },
        )
        assert draining.status_code == 200, draining.text
        assert draining.json()["state"] == "draining"
        assert draining.json()["reason_code"] == "ACTIVE_RUN_DRAIN_REQUIRED"
        assert draining.json()["verification_evidence_ref"] is None
