from __future__ import annotations

from services.notification_events import parse_domain_event, render_notification
from services.notification_telegram import format_telegram_message


def test_campaign_notification_uses_relative_link_without_public_frontend_url(monkeypatch):
    monkeypatch.delenv("DEVICE_FARM_FRONTEND_URL", raising=False)
    monkeypatch.delenv("FRONTEND_URL", raising=False)

    from core.env import device_farm_frontend_url

    event = parse_domain_event(
        {
            "type": "campaign.failed",
            "org_id": "org-1",
            "campaign_id": "camp-1",
            "resource_name": "test12",
            "status": "failed",
            "execution_completed": 0,
            "execution_failed": 1,
            "execution_cancelled": 0,
            "dispatch_id": "run-1",
            "error_message": "all_executions_dlq_open",
        }
    )
    rendered = render_notification(event, app_base_url=device_farm_frontend_url(fallback=""))

    assert "localhost" not in rendered.body
    assert rendered.deep_link == "/dashboard/campaigns/camp-1/monitor"
    assert "Open: /dashboard/campaigns/camp-1/monitor" in rendered.body


def test_format_telegram_campaign_dispatched():
    event = parse_domain_event(
        {
            "type": "campaign.dispatched",
            "org_id": "org-1",
            "campaign_id": "camp-1",
            "resource_name": "test12",
            "status": "running",
            "execution_total": 1,
            "dispatch_id": "eca094c8-17b9-4165-ae45-3ac65ff41b6c",
        }
    )
    rendered = render_notification(event, app_base_url="http://localhost:3000")
    text = format_telegram_message(
        event=event.event_type,
        title=rendered.title,
        body=rendered.body,
        data={"deep_link": rendered.deep_link},
    )

    assert text.startswith("🚀 <b>Campaign test12 dispatched</b>")
    assert "• <b>Status:</b> running" in text
    assert "• <b>Executions:</b> 1" in text
    assert "<code>eca094c8…</code>" in text
    assert 'href="http://localhost:3000/dashboard/campaigns/camp-1/monitor"' in text
    assert "Open dashboard" in text


def test_format_telegram_campaign_step_warning_wraps_error():
    event = parse_domain_event(
        {
            "type": "campaign.step_warning",
            "org_id": "org-1",
            "campaign_id": "camp-1",
            "resource_name": "test12",
            "status": "warning",
            "execution_id": "8b218d96-db2b-4888-b983-9737d390d203",
            "device_serial": "10AE7S00HD002JK",
            "step_index": 0,
            "step_type": "run_scenario",
            "error_message": (
                "run_scenario: sub-scenario failed — scroll_to description not found after 5 swipes"
            ),
        }
    )
    rendered = render_notification(event, app_base_url="http://localhost:3000")
    text = format_telegram_message(
        event=event.event_type,
        title=rendered.title,
        body=rendered.body,
        data={"deep_link": rendered.deep_link},
    )

    assert text.startswith("⚠️ <b>Campaign test12 step warning</b>")
    assert "• <b>Device:</b> 10AE7S00HD002JK" in text
    assert "<pre>run_scenario: sub-scenario failed" in text
    assert "<code>8b218d96…</code>" in text


def test_format_telegram_device_online():
    text = format_telegram_message(
        event="device.reconnect",
        title="Device vivo V2352A reconnected",
        body="vivo V2352A is online",
    )
    assert text.startswith("🟢 <b>Device vivo V2352A reconnected</b>")
    assert "vivo V2352A is online" in text


def test_format_telegram_account_verification_required():
    text = format_telegram_message(
        event="account.verification_required",
        title="Account fb-user needs verification",
        body=(
            "facebook:fb-user is held in verification until "
            "2026-09-27T12:00:00+00:00.\n"
            "Reminder: 2026-09-27T12:00:00+00:00\n"
            "Open: http://localhost:3000/dashboard/accounts"
        ),
        data={"deep_link": "http://localhost:3000/dashboard/accounts"},
    )
    assert text.startswith("🔐 <b>Account fb-user needs verification</b>")
    assert "• <b>Reminder:</b> 2026-09-27T12:00:00+00:00" in text
    assert "Open dashboard" in text


def test_format_telegram_vietnamese_link_label():
    event = parse_domain_event(
        {
            "type": "campaign.completed",
            "org_id": "org-1",
            "campaign_id": "camp-1",
            "resource_name": "test12",
            "status": "completed",
            "collected_count": 0,
            "execution_completed": 1,
            "execution_failed": 0,
            "execution_cancelled": 0,
        }
    )
    rendered = render_notification(event, locale="vi", app_base_url="http://localhost:3000")
    text = format_telegram_message(
        event=event.event_type,
        title=rendered.title,
        body=rendered.body,
        data={"deep_link": rendered.deep_link},
    )

    assert "da hoan thanh" in rendered.title
    assert "Mo dashboard" in text
    assert "Trang thai" in text
