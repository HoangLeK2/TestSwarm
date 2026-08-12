from dataclasses import replace
from types import SimpleNamespace

import pytest
from temporalio.service import RPCError, RPCStatusCode

from api.routes.campaigns import (
    _continuous_workflow_exists,
    _map_continuous_crawl_progress,
    continuous_crawl_preflight,
)
from services.campaign.aggregator import evaluate_campaign_status
from temporal.continuous_crawl_workflows import ContinuousCrawlProgress


@pytest.mark.asyncio
async def test_preflight_uses_all_assigned_eligible_devices(monkeypatch):
    campaign = SimpleNamespace(id="campaign-1")
    prepared = SimpleNamespace(
        devices=[
            SimpleNamespace(
                id=f"device-{index}",
                serial=f"serial-{index}",
                name=f"Phone {index}",
            )
            for index in range(3)
        ],
        available_count=6,
        target_counts={
            "device-0": 1,
            "device-1": 2,
            "device-2": 3,
        },
        config=SimpleNamespace(max_concurrency=1),
    )

    async def get_campaign(*_args, **_kwargs):
        return campaign

    async def require_temporal(_request):
        return SimpleNamespace()

    async def prepare(*_args, **_kwargs):
        return prepared

    monkeypatch.setattr("api.routes.campaigns._get_campaign_or_404", get_campaign)
    monkeypatch.setattr(
        "api.routes.campaigns._require_continuous_temporal", require_temporal
    )
    monkeypatch.setattr("api.routes.campaigns._prepare_continuous_crawl", prepare)

    result = await continuous_crawl_preflight(
        "campaign-1",
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(org_id="org-1"),
    )

    assert result.device_count == 3
    assert result.max_concurrency == 3
    assert result.target_count == 6
    assert [item.target_count for item in result.device_targets] == [1, 2, 3]


def test_maps_aggregate_progress_to_bounded_frontend_shape():
    raw = ContinuousCrawlProgress(
        loaded=12,
        active=2,
        succeeded=8,
        failed=2,
        device_lanes=[
            {
                "device_serial": "device-1",
                "status": "running",
                "completed": 8,
                "failed": 2,
            }
        ],
        recent_targets=[{"target_id": "entity-1", "status": "running"}],
    )

    result = _map_continuous_crawl_progress(
        "campaign-1",
        {"dispatch_id": "dispatch-1", "max_targets": 100},
        raw,
    )

    assert result.campaign_id == "campaign-1"
    assert result.dispatch_id == "dispatch-1"
    assert result.health == "degraded"
    assert result.max_targets == 100
    assert result.device_lanes[0].device_serial == "device-1"
    assert result.device_lanes[0].completed == 8
    assert result.recent_targets[0].target_id == "entity-1"


def test_progress_health_is_critical_for_failed_or_open_breaker():
    failed = ContinuousCrawlProgress(status="failed", failed=1)
    consecutive = replace(failed, status="running", consecutive_failures=10)

    assert _map_continuous_crawl_progress("c", {}, failed).health == "critical"
    assert _map_continuous_crawl_progress("c", {}, consecutive).health == "critical"


def test_progress_rows_are_bounded():
    raw = {
        "status": "running",
        "device_lanes": [
            {"device_serial": str(i), "status": "running"} for i in range(20)
        ],
        "recent_targets": [
            {"target_id": str(i), "status": "queued"} for i in range(20)
        ],
    }

    result = _map_continuous_crawl_progress("c", {}, raw)

    assert len(result.device_lanes) == 12
    assert len(result.recent_targets) == 8


@pytest.mark.asyncio
async def test_workflow_existence_only_swallows_temporal_not_found():
    class Handle:
        def __init__(self, error=None):
            self.error = error

        async def describe(self):
            if self.error:
                raise self.error
            return SimpleNamespace(status="running")

    class Client:
        def __init__(self, handle):
            self.handle = handle

        def get_workflow_handle(self, _workflow_id):
            return self.handle

    assert await _continuous_workflow_exists(Client(Handle()), "workflow-1")
    missing = RPCError("missing", RPCStatusCode.NOT_FOUND, b"")
    assert not await _continuous_workflow_exists(Client(Handle(missing)), "workflow-1")
    unavailable = RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")
    with pytest.raises(RPCError):
        await _continuous_workflow_exists(Client(Handle(unavailable)), "workflow-1")


@pytest.mark.asyncio
async def test_aggregator_does_not_complete_an_active_continuous_crawl(monkeypatch):
    campaign = SimpleNamespace(
        id="campaign-1",
        org_id="org-1",
        status="running",
        variables={"_continuous_crawl": {"active": True, "dispatch_id": "dispatch-1"}},
    )

    async def get_campaign_entity(_db, _campaign_id):
        return campaign

    monkeypatch.setattr(
        "db.crud.campaign_entity.get_campaign_entity",
        get_campaign_entity,
    )

    assert (
        await evaluate_campaign_status(
            SimpleNamespace(),
            org_id="org-1",
            campaign_id="campaign-1",
        )
        is None
    )
