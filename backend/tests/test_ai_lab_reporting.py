from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.ai_device_lab.readiness import materialize_service_slots
from services.ai_device_lab.report_pdf import (
    ReportPdfInvariantError,
    publish_report_pdf,
    render_report_pdf,
)
from services.ai_device_lab.reporting import BuildReport, attach_pdf_output, build_report_snapshot
from services.ai_device_lab.service_campaigns import CreateServiceCampaign, create_service_campaign
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, USER_A, seed_two_org_fixture


class _PrivateStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_private(self, *, object_key: str, data: bytes, content_type: str) -> bool:
        assert content_type == "application/pdf"
        self.objects[object_key] = data
        return True


@pytest.mark.asyncio
async def test_report_manifest_is_idempotent_and_pdf_must_match_manifest_hash(
    tenancy_session_factory,
    monkeypatch,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    cutoff = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await create_service_campaign(
                db,
                CreateServiceCampaign(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    package_name="com.example.app",
                    timezone="UTC",
                    plan_version="adl-14d-v1",
                ),
            )
            campaign.started_at = datetime(2026, 10, 4, tzinfo=timezone.utc)
            campaign.status = "active"
            await db.flush()
            await materialize_service_slots(db, org_id=ORG_A, service_campaign_id=campaign.id)
            command = BuildReport(
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                idempotency_key="report-cutoff-1",
                schema_version="adl-report-v1",
                builder_version="backend-test",
                cutoff_at=cutoff,
                created_by=USER_A,
            )
            first = await build_report_snapshot(db, command)
            replay = await build_report_snapshot(db, command)
            with pytest.raises(ValueError, match="report idempotency key"):
                await build_report_snapshot(
                    db,
                    BuildReport(
                        org_id=ORG_A,
                        service_campaign_id=campaign.id,
                        idempotency_key="report-cutoff-1",
                        schema_version="adl-report-v2",
                        builder_version="backend-test",
                        cutoff_at=cutoff,
                        created_by=USER_A,
                    ),
                )
            with pytest.raises(ValueError):
                await attach_pdf_output(
                    db,
                    org_id=ORG_A,
                    report_id=first.id,
                    manifest_sha256="0" * 64,
                    object_key="reports/wrong.pdf",
                    pdf_sha256="1" * 64,
                )
            pdf = render_report_pdf(first)
            assert pdf.startswith(b"%PDF-1.4")
            assert pdf.endswith(b"%%EOF\n")
            assert b"source_ids" not in pdf
            assert pdf == render_report_pdf(first)

            monkeypatch.delenv("AI_DEVICE_LAB_PRIVATE_REPORT_STORAGE_CONFIRMED", raising=False)
            with pytest.raises(ReportPdfInvariantError, match="unavailable or unconfirmed"):
                await publish_report_pdf(db, org_id=ORG_A, report_id=first.id)

            storage = _PrivateStorage()
            published = await publish_report_pdf(
                db, org_id=ORG_A, report_id=first.id, storage=storage
            )
            replay_publish = await publish_report_pdf(
                db, org_id=ORG_A, report_id=first.id, storage=storage
            )

    assert replay.id == first.id
    assert first.manifest["service"]["planned_slots"] == 168
    assert published.status == "published"
    assert published.pdf_sha256 is not None
    assert published.pdf_object_key in storage.objects
    assert replay_publish.id == published.id
    assert len(storage.objects) == 1
