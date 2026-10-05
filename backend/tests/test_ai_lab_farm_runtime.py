from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from temporalio.exceptions import WorkflowAlreadyStartedError

from db.models.ai_device_lab import (
    AppBuild,
    RunAttempt,
    RunSlot,
    ScenarioApproval,
    ServiceCampaign,
    ServiceLane,
)
from db.models.ai_device_lab_delivery import FarmJob
from db.models.ai_device_lab_fleet import DeviceReservation
from db.models.device import Device
from db.models.execution import Execution
from services.ai_device_lab.delivery import (
    CreateFarmJob,
    FarmDeliveryError,
    create_farm_job,
    run_farm_delivery_batch,
)
from services.ai_device_lab.farm_runtime import FallbackFarmJobSink, TemporalFarmJobSink
from services.operation_policy import OperationPolicy
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, ORG_B, USER_A
from tests.test_ai_lab_billing_checkout import _seed_approved_campaign


class IdempotentTemporalClient:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []
        self.result_event = asyncio.Event()

    class _Handle:
        def __init__(self, event: asyncio.Event) -> None:
            self._event = event

        async def result(self):
            await self._event.wait()
            return SimpleNamespace(success=True)

        async def cancel(self) -> None:
            self._event.set()

    async def start_workflow(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if len(self.calls) > 1:
            raise WorkflowAlreadyStartedError(
                kwargs["id"],
                "ScenarioWorkflow",
                run_id="existing-run",
            )

    def get_workflow_handle(self, _workflow_id: str):
        return self._Handle(self.result_event)


class _BuildClient:
    def __init__(self, version_name: str = "1.0.0", version_code: str = "100") -> None:
        self.version_name = version_name
        self.version_code = version_code

    def shell_sync(self, _command: str, timeout: float = 10.0) -> str:
        return f"versionCode={self.version_code} minSdk=23\nversionName={self.version_name}\n"


class _BuildManager:
    def __init__(self, version_name: str = "1.0.0", version_code: str = "100") -> None:
        self.client = _BuildClient(version_name, version_code)

    def get_device(self, _serial: str) -> _BuildClient:
        return self.client


def _runtime_task(kwargs: dict, scheduled: list) -> asyncio.Task[None]:
    scheduled.append(kwargs)

    async def _wait_for_cancel() -> None:
        while not kwargs["cancel_event"].is_set():
            await asyncio.sleep(0.005)

    return asyncio.create_task(_wait_for_cancel())


async def _seed_farm_job(session_factory) -> dict:
    campaign_id, approval_id = await _seed_approved_campaign(session_factory)
    now = datetime.now(UTC).replace(microsecond=0)
    with tenant_context(ORG_A):
        async with session_factory() as db:
            campaign = await db.get(ServiceCampaign, campaign_id)
            approval = await db.get(ScenarioApproval, approval_id)
            lane = (
                await db.execute(
                    select(ServiceLane)
                    .where(ServiceLane.service_campaign_id == campaign_id)
                    .order_by(ServiceLane.ordinal)
                    .limit(1)
                )
            ).scalar_one()
            assert campaign is not None and approval is not None
            device = Device(
                id="adl-farm-runtime-device",
                org_id=ORG_A,
                user_id=USER_A,
                serial="ADL-FARM-RUNTIME-01",
                name="ADL farm runtime",
                last_seen=now,
            )
            build = AppBuild(
                id="adl-farm-runtime-build",
                org_id=ORG_A,
                package_name=approval.package_name,
                version_name="1.0.0",
                version_code="100",
                source_kind="closed_track",
                source_ref="play-closed-track",
            )
            slot = RunSlot(
                id="adl-farm-runtime-slot",
                org_id=ORG_A,
                service_campaign_id=campaign_id,
                lane_id=lane.id,
                service_day=1,
                planned_at=now,
                execution_status="scheduled",
                play_participation_state="unknown",
            )
            execution = Execution(
                id="adl-farm-runtime-execution",
                run_type="ai_device_lab",
                kind="campaign",
                status="pending",
                org_id=ORG_A,
                campaign_id=campaign.runtime_campaign_id,
                scenario_version_id=approval.scenario_version_id,
                user_id=USER_A,
                device_config={"device_id": device.id, "device_serial": device.serial},
                meta={},
            )
            reservation = DeviceReservation(
                id="adl-farm-runtime-reservation",
                org_id=ORG_A,
                service_campaign_id=campaign_id,
                lane_id=lane.id,
                device_id=device.id,
                starts_at=now - timedelta(minutes=1),
                ends_at=now + timedelta(days=14),
                state="active",
                created_by=USER_A,
            )
            attempt = RunAttempt(
                id="adl-farm-runtime-attempt",
                org_id=ORG_A,
                service_campaign_id=campaign_id,
                lane_id=lane.id,
                slot_id=slot.id,
                attempt_no=1,
                execution_id=execution.id,
                scenario_version_id=approval.scenario_version_id,
                app_build_id=build.id,
                idempotency_key="adl-farm-runtime-attempt-key",
                reason="scheduled",
                status="created",
                observed_build={"version_code": "100"},
            )
            db.add_all([device, build, slot, execution, reservation, attempt])
            await db.flush()
            job = await create_farm_job(
                db,
                CreateFarmJob(
                    org_id=ORG_A,
                    run_attempt_id=attempt.id,
                    reservation_id=reservation.id,
                    approval_id=approval.id,
                    idempotency_key="adl-farm-runtime-job-key",
                    deadline_at=now + timedelta(minutes=5),
                    active_policy=OperationPolicy(
                        version=approval.policy_version,
                        app_package=approval.package_name,
                        allowed_actions=frozenset(approval.allowed_operations),
                        allowed_targets=frozenset({approval.package_name}),
                    ),
                ),
            )
            await db.commit()
            return {
                "payload": dict(job.payload),
                "job_id": job.id,
                "execution_id": execution.id,
                "attempt_id": attempt.id,
                "runtime_campaign_id": campaign.runtime_campaign_id,
                "device_serial": device.serial,
            }


@pytest.mark.asyncio
async def test_temporal_farm_sink_dispatches_exact_snapshot_and_replay_is_safe(
    tenancy_session_factory,
) -> None:
    seeded = await _seed_farm_job(tenancy_session_factory)
    client = IdempotentTemporalClient()
    sink = TemporalFarmJobSink(
        temporal_client=client,
        session_factory=tenancy_session_factory,
        task_queue="device-scenario-test",
        manager=_BuildManager(),
    )

    result = await run_farm_delivery_batch(
        tenancy_session_factory,
        sink=sink,
        batch_size=10,
    )
    await sink.deliver(seeded["payload"])

    assert result.delivered == 1
    assert len(client.calls) == 2
    first_args, first_kwargs = client.calls[0]
    scenario_input = first_args[1]
    assert first_kwargs["id"] == f"exec_{seeded['execution_id']}"
    assert first_kwargs["task_queue"] == "device-scenario-test"
    assert scenario_input.campaign_id == seeded["runtime_campaign_id"]
    assert scenario_input.device_serial == seeded["device_serial"]
    assert scenario_input.execution_id == seeded["execution_id"]
    assert scenario_input.steps
    assert "secret" not in str(first_kwargs).lower()

    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            execution = await db.get(Execution, seeded["execution_id"])
            attempt = await db.get(RunAttempt, seeded["attempt_id"])
            job = await db.get(FarmJob, seeded["job_id"])
            assert execution is not None and attempt is not None and job is not None
            assert execution.status == "running"
            assert execution.meta["workflow_id"] == first_kwargs["id"]
            assert execution.meta["dispatch_source"] == "ai_device_lab_farm_outbox"
            assert attempt.status == "dispatched"
            assert job.status == "dispatched"
            assert attempt.observed_build["version_name"] == "1.0.0"
            assert attempt.observed_build["version_code"] == "100"

    client.result_event.set()
    await asyncio.sleep(0.05)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            execution = await db.get(Execution, seeded["execution_id"])
            attempt = await db.get(RunAttempt, seeded["attempt_id"])
            job = await db.get(FarmJob, seeded["job_id"])
            slot = await db.get(RunSlot, "adl-farm-runtime-slot")
            assert execution is not None and execution.status == "completed"
            assert attempt is not None and attempt.status == "passed"
            assert job is not None and job.status == "succeeded"
            assert slot is not None and slot.execution_status == "completed"

    await sink.aclose()


@pytest.mark.asyncio
async def test_temporal_farm_sink_fails_closed_for_secret_or_wrong_tenant(
    tenancy_session_factory,
) -> None:
    seeded = await _seed_farm_job(tenancy_session_factory)
    client = IdempotentTemporalClient()
    sink = TemporalFarmJobSink(
        temporal_client=client,
        session_factory=tenancy_session_factory,
        task_queue="device-scenario-test",
        manager=_BuildManager(),
    )
    secret_payload = {**seeded["payload"], "secret_capability_ref": "opaque-secret-ref"}
    wrong_tenant = {**seeded["payload"], "org_id": ORG_B}

    with pytest.raises(FarmDeliveryError) as secret_error:
        await sink.deliver(secret_payload)
    with pytest.raises(FarmDeliveryError) as tenant_error:
        await sink.deliver(wrong_tenant)

    assert secret_error.value.code == "SECRET_CAPABILITY_RUNTIME_UNAVAILABLE"
    assert tenant_error.value.code == "FARM_JOB_SCOPE_INVALID"
    assert client.calls == []


@pytest.mark.asyncio
async def test_temporal_farm_sink_waits_for_cancel_drain_before_deadline_verdict(
    tenancy_session_factory,
) -> None:
    seeded = await _seed_farm_job(tenancy_session_factory)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            job = await db.get(FarmJob, seeded["job_id"])
            assert job is not None
            job.deadline_at = datetime.now(UTC) + timedelta(milliseconds=50)
            job.payload = {**job.payload, "deadline_at": job.deadline_at.isoformat()}
            seeded["payload"] = dict(job.payload)
            await db.commit()
    client = IdempotentTemporalClient()
    sink = TemporalFarmJobSink(
        temporal_client=client,
        session_factory=tenancy_session_factory,
        task_queue="device-scenario-test",
        manager=_BuildManager(),
        cancellation_drain_seconds=0.2,
    )

    await sink.deliver(seeded["payload"])
    await asyncio.sleep(0.1)

    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            attempt = await db.get(RunAttempt, seeded["attempt_id"])
            job = await db.get(FarmJob, seeded["job_id"])
            assert attempt is not None and attempt.status == "blocked"
            assert attempt.failure_reason == "DEADLINE_EXCEEDED"
            assert job is not None and job.status == "blocked"
    await sink.aclose()


@pytest.mark.asyncio
async def test_farm_sink_rejects_observed_build_mismatch_before_dispatch(
    tenancy_session_factory,
) -> None:
    seeded = await _seed_farm_job(tenancy_session_factory)
    client = IdempotentTemporalClient()
    sink = TemporalFarmJobSink(
        temporal_client=client,
        session_factory=tenancy_session_factory,
        task_queue="device-scenario-test",
        manager=_BuildManager(version_name="2.0.0", version_code="200"),
    )

    with pytest.raises(FarmDeliveryError) as error:
        await sink.deliver(seeded["payload"])

    assert error.value.code == "OBSERVED_BUILD_MISMATCH"
    assert client.calls == []
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            attempt = await db.get(RunAttempt, seeded["attempt_id"])
            assert attempt is not None
            assert attempt.observed_build["version_name"] == "2.0.0"
            assert attempt.observed_build["target_app_build_id"] == "adl-farm-runtime-build"


@pytest.mark.asyncio
async def test_fallback_farm_sink_reuses_shared_runtime_and_persists_terminal_event(
    tenancy_session_factory,
    monkeypatch,
) -> None:
    seeded = await _seed_farm_job(tenancy_session_factory)
    scheduled: list[dict] = []

    def fake_schedule_fallback_runtime(**kwargs):
        return _runtime_task(kwargs, scheduled)

    monkeypatch.setattr(
        "services.ai_device_lab.farm_runtime.schedule_fallback_runtime",
        fake_schedule_fallback_runtime,
    )
    sink = FallbackFarmJobSink(
        session_factory=tenancy_session_factory,
        manager=_BuildManager(),
        completion_poll_seconds=0.01,
    )

    await sink.deliver(seeded["payload"])
    await sink._record_terminal(
        sink._prepared_by_execution[seeded["execution_id"]],
        status="completed",
        source="fallback-runtime",
    )

    assert len(scheduled) == 1
    assert scheduled[0]["scenario_input"].device_serial == seeded["device_serial"]
    assert scheduled[0]["execution_id"] == seeded["execution_id"]
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            execution = await db.get(Execution, seeded["execution_id"])
            attempt = await db.get(RunAttempt, seeded["attempt_id"])
            job = await db.get(FarmJob, seeded["job_id"])
            assert execution is not None and attempt is not None and job is not None
            assert execution.meta["runtime_engine"] == "fallback"
            assert attempt.status == "passed"
            assert attempt.outcome == "pass"
            assert job.status == "succeeded"
            assert job.verdict == "pass"

    await sink.aclose()


@pytest.mark.asyncio
async def test_fallback_farm_sink_does_not_blindly_repeat_uncertain_dispatch(
    tenancy_session_factory,
    monkeypatch,
) -> None:
    seeded = await _seed_farm_job(tenancy_session_factory)
    scheduled: list[str] = []
    monkeypatch.setattr(
        "services.ai_device_lab.farm_runtime.schedule_fallback_runtime",
        lambda **kwargs: _runtime_task(kwargs, scheduled),
    )
    first = FallbackFarmJobSink(
        session_factory=tenancy_session_factory,
        manager=_BuildManager(),
    )
    replay = FallbackFarmJobSink(
        session_factory=tenancy_session_factory,
        manager=_BuildManager(),
    )

    await first.deliver(seeded["payload"])
    with pytest.raises(FarmDeliveryError) as error:
        await replay.deliver(seeded["payload"])

    assert error.value.code == "FALLBACK_DISPATCH_UNCERTAIN"
    assert [item["execution_id"] for item in scheduled] == [seeded["execution_id"]]
    await first.aclose()
    await replay.aclose()


@pytest.mark.asyncio
async def test_fallback_farm_sink_deadline_sets_cancel_signal_before_blocking(
    tenancy_session_factory,
    monkeypatch,
) -> None:
    seeded = await _seed_farm_job(tenancy_session_factory)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            job = await db.get(FarmJob, seeded["job_id"])
            assert job is not None
            job.deadline_at = datetime.now(UTC) + timedelta(milliseconds=80)
            await db.commit()
    scheduled: list[dict] = []
    monkeypatch.setattr(
        "services.ai_device_lab.farm_runtime.schedule_fallback_runtime",
        lambda **kwargs: _runtime_task(kwargs, scheduled),
    )
    sink = FallbackFarmJobSink(
        session_factory=tenancy_session_factory,
        manager=_BuildManager(),
        completion_poll_seconds=0.01,
    )

    await sink.deliver(seeded["payload"])
    await asyncio.sleep(0.12)

    assert len(scheduled) == 1
    assert scheduled[0]["cancel_event"].is_set() is True
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            attempt = await db.get(RunAttempt, seeded["attempt_id"])
            job = await db.get(FarmJob, seeded["job_id"])
            assert attempt is not None and job is not None
            assert attempt.status == "blocked"
            assert attempt.failure_reason == "DEADLINE_EXCEEDED"
            assert job.status == "blocked"
            assert job.terminal_reason == "DEADLINE_EXCEEDED"
    await sink.aclose()
