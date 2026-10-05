from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from db.models.ai_device_lab_participation import ParticipationEvent, TrackParticipation
from services.ai_device_lab.participation import RecordParticipation, record_participation
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, USER_A, seed_two_org_fixture


@pytest.mark.asyncio
async def test_twelve_accounts_are_distinct_and_repeat_identity_does_not_add_a_thirteenth(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    observed = datetime(2026, 10, 4, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            for ordinal in range(1, 13):
                await record_participation(
                    db,
                    RecordParticipation(
                        org_id=ORG_A,
                        package_name="com.example.app",
                        track_name="closed",
                        pseudonymous_account_ref=f"account-{ordinal:02d}",
                        masked_label=f"tester-{ordinal:02d}",
                        event_type="opted_in",
                        source_type="operator_observation",
                        evidence_grade="operator_attested",
                        observed_at=observed,
                        recorded_by=USER_A,
                        reviewed_by=USER_A,
                    ),
                )
            await record_participation(
                db,
                RecordParticipation(
                    org_id=ORG_A,
                    package_name="com.example.app",
                    track_name="closed",
                    pseudonymous_account_ref="account-01",
                    masked_label="same-account-new-device",
                    event_type="opened",
                    source_type="operator_observation",
                    evidence_grade="operator_attested",
                    observed_at=observed + timedelta(minutes=1),
                    recorded_by=USER_A,
                    reviewed_by=USER_A,
                ),
            )
            await db.commit()
            identities = await db.scalar(
                select(func.count()).select_from(TrackParticipation)
            )
            events = await db.scalar(select(func.count()).select_from(ParticipationEvent))

    assert identities == 12
    assert events == 13


@pytest.mark.asyncio
async def test_lost_and_rejoined_create_new_segment_while_late_event_keeps_projection(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    first = datetime(2026, 10, 1, tzinfo=timezone.utc)
    common = {
        "org_id": ORG_A,
        "package_name": "com.example.app",
        "track_name": "closed",
        "pseudonymous_account_ref": "account-continuity",
        "masked_label": "tester-continuity",
        "source_type": "operator_observation",
        "evidence_grade": "operator_attested",
        "recorded_by": USER_A,
        "reviewed_by": USER_A,
    }
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            identity, _ = await record_participation(
                db, RecordParticipation(**common, event_type="opted_in", observed_at=first)
            )
            await record_participation(
                db,
                RecordParticipation(
                    **common,
                    event_type="lost",
                    observed_at=first + timedelta(days=2),
                ),
            )
            await record_participation(
                db,
                RecordParticipation(
                    **common,
                    event_type="rejoined",
                    observed_at=first + timedelta(days=3),
                ),
            )
            await record_participation(
                db,
                RecordParticipation(
                    **common,
                    event_type="lost",
                    observed_at=first + timedelta(days=1),
                    limitations="late observation",
                ),
            )
            await db.commit()
            await db.refresh(identity)
            event_count = await db.scalar(
                select(func.count()).select_from(ParticipationEvent)
            )

    assert identity.current_status == "opted_in"
    assert identity.active_segment_no == 2
    assert identity.last_observed_at.replace(tzinfo=timezone.utc) == first + timedelta(days=3)
    assert event_count == 4
