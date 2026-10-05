from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from api.deps import _get_current_user
from db.models.activity import ActivityLog
from db.models.notification import Notification
from tests.tenancy_test_support import (
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    api_client_for_user,
    build_tenancy_api_app,
    seed_two_org_fixture,
)


def test_epic09_event_schema_template_and_safe_adhoc_contract():
    from services.notification_events import (
        EventSchemaError,
        build_deep_link,
        parse_domain_event,
        render_notification,
    )
    from services.analytics_query import AnalyticsQuery, AnalyticsQueryError

    with pytest.raises(EventSchemaError) as exc:
        parse_domain_event({"type": "schedule.run_failed", "org_id": ORG_A})
    assert exc.value.code == "EVENT_SCHEMA_INVALID"
    assert "schedule_id" in str(exc.value)

    event = parse_domain_event(
        {
            "type": "campaign.completed",
            "org_id": ORG_A,
            "campaign_id": "camp-a-1",
            "execution_id": "exec-1",
            "actor_user_id": USER_A,
            "summary": "42 items collected",
        }
    )
    assert event.event_type == "campaign.completed"
    assert event.resource_type == "campaign"
    assert event.resource_id == "camp-a-1"

    rendered = render_notification(
        event,
        locale="vi",
        app_base_url="https://farm.example",
    )
    assert "hoan thanh" in rendered.title.lower()
    assert rendered.deep_link == "https://farm.example/dashboard/campaigns/camp-a-1/monitor"
    assert build_deep_link("device", "serial-1", "https://farm.example/") == (
        "https://farm.example/devices/serial-1"
    )

    query = AnalyticsQuery(
        metric="count",
        dimensions=["event_type"],
        filters={"event_type": "campaign.completed"},
        from_date=date(2026, 5, 1),
        to_date=date(2026, 5, 7),
        limit=25,
    )
    assert query.limit == 25
    with pytest.raises(AnalyticsQueryError) as exc:
        AnalyticsQuery(
            metric="count",
            dimensions=["event_type; DROP TABLE users"],
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 2),
        )
    assert exc.value.code == "UNSUPPORTED_DIMENSION"


def test_campaign_notification_templates_include_operational_payload():
    from services.notification_events import (
        lint_templates,
        parse_domain_event,
        render_notification,
    )

    completed = parse_domain_event(
        {
            "type": "campaign.completed",
            "org_id": ORG_A,
            "campaign_id": "camp-a-1",
            "resource_name": "Instagram comment crawl",
            "status": "completed",
            "collected_count": 128,
            "execution_completed": 4,
            "execution_failed": 0,
        }
    )
    rendered_completed = render_notification(
        completed,
        app_base_url="https://farm.example",
    )
    assert rendered_completed.title == "Campaign Instagram comment crawl completed"
    assert "Status: completed" in rendered_completed.body
    assert "Collected: 128 items" in rendered_completed.body
    assert "Executions: 4 completed, 0 failed" in rendered_completed.body

    failed = parse_domain_event(
        {
            "type": "campaign.failed",
            "org_id": ORG_A,
            "campaign_id": "camp-a-1",
            "campaign_name": "Instagram comment crawl",
            "status": "failed",
            "content_count": "37",
            "completed_executions": 1,
            "failed_executions": 3,
            "reason": "executions_failed",
        }
    )
    rendered_failed = render_notification(
        failed,
        app_base_url="https://farm.example",
    )
    assert rendered_failed.title == "Campaign Instagram comment crawl failed"
    assert "Error: executions_failed" in rendered_failed.body
    assert "Collected: 37 items" in rendered_failed.body
    assert "Executions: 1 completed, 3 failed" in rendered_failed.body

    dispatched = parse_domain_event(
        {
            "type": "campaign.dispatched",
            "org_id": ORG_A,
            "campaign_id": "camp-a-1",
            "resource_name": "Instagram comment crawl",
            "status": "running",
            "execution_total": 4,
        }
    )
    rendered_dispatched = render_notification(
        dispatched,
        locale="vi",
        app_base_url="https://farm.example",
    )
    assert rendered_dispatched.title == "Campaign Instagram comment crawl da dispatch"
    assert "Trang thai: running" in rendered_dispatched.body
    assert "Executions: 4" in rendered_dispatched.body

    warning = parse_domain_event(
        {
            "type": "campaign.step_warning",
            "org_id": ORG_A,
            "campaign_id": "camp-a-1",
            "resource_name": "Instagram comment crawl",
            "status": "warning",
            "execution_id": "exec-1",
            "device_serial": "serial-1",
            "step_index": 2,
            "step_type": "run_scenario",
            "error_message": "incident recovery playbooks did not resolve the step",
        }
    )
    rendered_warning = render_notification(
        warning,
        app_base_url="https://farm.example",
    )
    assert rendered_warning.title == "Campaign Instagram comment crawl step warning"
    assert "Step: run_scenario #2" in rendered_warning.body
    assert "Device: serial-1" in rendered_warning.body
    assert "Campaign continues" in rendered_warning.body

    verification = parse_domain_event(
        {
            "type": "account.verification_required",
            "org_id": ORG_A,
            "account_id": "acc-a-1",
            "resource_name": "platform-user",
            "summary": "instagram:platform-user is held in verification until 2026-09-27T12:00:00+00:00.",
            "remind_at": "2026-09-27T12:00:00+00:00",
        }
    )
    rendered_verification = render_notification(
        verification,
        locale="vi",
        app_base_url="https://farm.example",
    )
    assert rendered_verification.title == "Tai khoan platform-user can xac thuc"
    assert "Nhac lai: 2026-09-27T12:00:00+00:00" in rendered_verification.body

    assert lint_templates() == []


@pytest.mark.asyncio
async def test_epic09_inbox_is_org_scoped_and_mark_read_returns_fresh_count(
    tenancy_session_factory,
):
    await seed_two_org_fixture(tenancy_session_factory)
    app = build_tenancy_api_app(tenancy_session_factory)
    now = datetime.now(timezone.utc)
    async with tenancy_session_factory() as db:
        db.add_all(
            [
                Notification(
                    id="notif-a",
                    event="campaign.completed",
                    title="A",
                    body="A body",
                    data={"deep_link": "/campaigns/camp-a-1"},
                    user_id=USER_A,
                    org_id=ORG_A,
                    created_at=now,
                    sent_at=now,
                ),
                Notification(
                    id="notif-b",
                    event="campaign.completed",
                    title="B",
                    body="B body",
                    user_id=USER_A,
                    org_id=ORG_B,
                    created_at=now,
                    sent_at=now,
                ),
            ]
        )
        await db.commit()

    async with api_client_for_user(app, USER_A, ORG_A) as client:
        count = await client.get("/api/notifications/unread-count")
        assert count.status_code == 200
        assert count.json() == {"count": 1}

        marked = await client.patch("/api/notifications/notif-a/read")
        assert marked.status_code == 200
        body = marked.json()
        assert body["id"] == "notif-a"
        assert body["is_read"] is True
        assert body["read_at"] is not None
        assert body["unread_count"] == 0

        missing = await client.patch("/api/notifications/notif-b/read")
        assert missing.status_code == 404

    async with tenancy_session_factory() as db:
        row = await db.get(Notification, "notif-a")
        assert row is not None
        assert row.read_at is not None


@pytest.mark.asyncio
async def test_epic09_analytics_timeseries_export_and_adhoc_are_tenant_safe(
    tenancy_session_factory,
):
    from db.models.analytics import MetricRollupDaily

    await seed_two_org_fixture(tenancy_session_factory)
    app = build_tenancy_api_app(tenancy_session_factory)
    day = date(2026, 5, 26)
    now = datetime(2026, 5, 26, 8, 0, tzinfo=timezone.utc)
    async with tenancy_session_factory() as db:
        db.add_all(
            [
                MetricRollupDaily(
                    org_id=ORG_A,
                    bucket_date=day,
                    resource_type="campaign",
                    resource_id="camp-a-1",
                    event_type="campaign.completed",
                    count=4,
                    success_count=4,
                    fail_count=0,
                ),
                MetricRollupDaily(
                    org_id=ORG_B,
                    bucket_date=day,
                    resource_type="campaign",
                    resource_id="camp-b-1",
                    event_type="campaign.failed",
                    count=99,
                    success_count=0,
                    fail_count=99,
                ),
                ActivityLog(
                    id="act-a",
                    org_id=ORG_A,
                    user_id=USER_A,
                    action="campaign.completed",
                    entity_type="campaign",
                    entity_id="camp-a-1",
                    request_id="req-secret",
                    details={"token": "secret-token", "count": 4},
                    created_at=now,
                ),
                ActivityLog(
                    id="act-b",
                    org_id=ORG_B,
                    user_id=USER_B,
                    action="campaign.failed",
                    entity_type="campaign",
                    entity_id="camp-b-1",
                    details={"count": 99},
                    created_at=now,
                ),
            ]
        )
        await db.commit()

    async with api_client_for_user(app, USER_A, ORG_A) as client:
        timeseries = await client.get(
            "/api/analytics/timeseries",
            params={
                "dimension": "campaign",
                "resource_id": "camp-a-1",
                "from": "2026-05-26",
                "to": "2026-05-26",
                "granularity": "day",
            },
        )
        assert timeseries.status_code == 200
        points = timeseries.json()["points"]
        assert points == [
            {
                "date": "2026-05-26",
                "resource_type": "campaign",
                "resource_id": "camp-a-1",
                "event_type": "campaign.completed",
                "count": 4,
                "success_count": 4,
                "fail_count": 0,
                "latency_p50": None,
                "latency_p95": None,
            }
        ]

        too_large = await client.get(
            "/api/analytics/timeseries",
            params={
                "dimension": "campaign",
                "from": "2026-01-01",
                "to": "2026-05-26",
                "granularity": "day",
            },
        )
        assert too_large.status_code == 400
        assert too_large.json()["detail"]["code"] == "WINDOW_TOO_LARGE"

        adhoc = await client.post(
            "/api/analytics/adhoc-query",
            json={
                "metric": "count",
                "dimensions": ["event_type"],
                "filters": {"event_type": "campaign.completed"},
                "from_date": "2026-05-26",
                "to_date": "2026-05-26",
                "limit": 10,
            },
        )
        assert adhoc.status_code == 200
        assert adhoc.json()["rows"] == [{"event_type": "campaign.completed", "count": 1}]

        report = await client.get(
            "/api/analytics/audit/export",
            params={"from": "2026-05-26", "to": "2026-05-26"},
        )
        assert report.status_code == 200
        assert "campaign.completed" in report.text
        assert "campaign.failed" not in report.text
        assert "secret-token" not in report.text
        assert "[REDACTED]" in report.text


def test_epic09_rollup_retention_alert_and_preference_primitives():
    from services.analytics_retention import RetentionPolicy, select_retention_cutoff
    from services.analytics_rollup import rollup_activity_rows
    from services.notification_alerts import (
        AlertRuleConfig,
        should_fire_alert,
        should_suppress_alert,
    )
    from services.notification_preferences import resolve_effective_preference

    rows = [
        {
            "org_id": ORG_A,
            "created_at": datetime(2026, 5, 26, 1, tzinfo=timezone.utc),
            "action": "campaign.completed",
            "entity_type": "campaign",
            "entity_id": "camp-a-1",
            "details": {"duration_ms": 10},
        },
        {
            "org_id": ORG_A,
            "created_at": datetime(2026, 5, 26, 2, tzinfo=timezone.utc),
            "action": "campaign.failed",
            "entity_type": "campaign",
            "entity_id": "camp-a-1",
            "details": {"duration_ms": 90},
        },
    ]
    rolled = rollup_activity_rows(rows, granularity="day")
    assert rolled[0]["count"] == 1
    assert {item["event_type"] for item in rolled} == {
        "campaign.completed",
        "campaign.failed",
    }

    policy = RetentionPolicy(
        org_id=ORG_A,
        data_type="activity_log",
        retention_days=180,
        action="purge",
        legal_hold=False,
    )
    assert select_retention_cutoff(policy, now=datetime(2026, 6, 1, tzinfo=timezone.utc)) == (
        datetime(2025, 12, 3, tzinfo=timezone.utc)
    )
    legal_hold = policy.model_copy(update={"legal_hold": True})
    assert select_retention_cutoff(legal_hold, now=datetime(2026, 6, 1, tzinfo=timezone.utc)) is None

    rule = AlertRuleConfig(
        metric="device.offline.count",
        comparator="gt",
        threshold=5,
        window_minutes=10,
        severity="critical",
    )
    assert should_fire_alert(rule, observed_value=6) is True
    assert should_suppress_alert(
        rule_id="rule-1",
        now=datetime(2026, 5, 26, 10, 5, tzinfo=timezone.utc),
        last_sent_at=datetime(2026, 5, 26, 10, 0, tzinfo=timezone.utc),
        suppression_minutes=10,
        severity="critical",
    ) is False

    effective = resolve_effective_preference(
        event_type="device.offline",
        channel="in_app",
        user_override=False,
        admin_override=None,
        default_enabled=True,
        mandatory=True,
    )
    assert effective.enabled is True
    assert effective.source == "mandatory"
    assert "cannot opt out" in effective.reason
