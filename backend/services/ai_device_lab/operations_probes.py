"""Bounded, redacted probes for short-lived operational readiness."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models.ai_device_lab_operations import (
    OperationalReadinessAssessment,
    OperationalTarget,
)
from services.ai_device_lab.operations import (
    REQUIRED_DEPENDENCIES,
    AssessOperationalReadiness,
    DependencyObservation,
    OperationalInvariantError,
    assess_operational_readiness,
)
from tenancy.context import tenant_context

_SAFE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
log = logging.getLogger(__name__)


class DependencyProbe(Protocol):
    async def probe(self, *, observed_at: datetime) -> DependencyObservation: ...


@dataclass(frozen=True, slots=True)
class RunOperationalProbes:
    org_id: str
    target_id: str
    build_ref: str
    schema_version: str
    observed_at: datetime
    ttl_seconds: int = 60
    timeout_seconds: float = 3
    max_observation_age_seconds: float = 15
    concurrency: int = 3


@dataclass(frozen=True, slots=True)
class OperationalProbeBatchResult:
    discovered: int
    assessed: int
    ready: int
    blocked: int
    skipped_fresh: int


class HttpStatusProbe:
    """Probe a configured HTTP dependency without persisting its endpoint."""

    def __init__(
        self,
        *,
        endpoint: str,
        source_ref: str,
        expected_statuses: frozenset[int] = frozenset({200}),
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise OperationalInvariantError("probe endpoint must be an HTTP(S) URL")
        if parsed.username or parsed.password:
            raise OperationalInvariantError("probe endpoint must not embed credentials")
        if not 1 <= len(source_ref) <= 128 or any(ord(c) < 32 for c in source_ref):
            raise OperationalInvariantError("probe source ref is invalid")
        if not expected_statuses or any(code < 100 or code > 599 for code in expected_statuses):
            raise OperationalInvariantError("probe expected statuses are invalid")
        self._endpoint = endpoint
        self._source_ref = source_ref
        self._expected_statuses = expected_statuses
        self._client = client

    async def probe(self, *, observed_at: datetime) -> DependencyObservation:
        started = time.perf_counter()
        owned_client = self._client is None
        client = self._client or httpx.AsyncClient(follow_redirects=False)
        try:
            response = await client.get(self._endpoint)
        finally:
            if owned_client:
                await client.aclose()
        ready = response.status_code in self._expected_statuses
        version_header = response.headers.get("x-service-version", "").strip()
        source_version = (
            version_header if _SAFE_VERSION.fullmatch(version_header) else None
        )
        return DependencyObservation(
            ready=ready,
            reason_code="PASS" if ready else "HTTP_STATUS_UNREADY",
            observed_at=observed_at,
            source_type="http_status",
            source_ref=self._source_ref,
            source_version=source_version,
            latency_ms=(time.perf_counter() - started) * 1000,
        )


_configured_probes: dict[str, DependencyProbe] = {}


def configure_operational_dependency_probe(
    dependency: str,
    probe: DependencyProbe | None,
) -> None:
    if dependency not in REQUIRED_DEPENDENCIES:
        raise OperationalInvariantError("unknown operational dependency probe")
    if probe is None:
        _configured_probes.pop(dependency, None)
    else:
        _configured_probes[dependency] = probe


def _blocked_observation(
    dependency: str,
    *,
    reason_code: str,
    observed_at: datetime,
    latency_ms: float = 0,
) -> DependencyObservation:
    return DependencyObservation(
        ready=False,
        reason_code=reason_code,
        observed_at=observed_at,
        source_type="dependency_probe",
        source_ref=dependency,
        source_version=None,
        latency_ms=latency_ms,
    )


async def collect_dependency_observations(
    probes: Mapping[str, DependencyProbe],
    *,
    observed_at: datetime,
    timeout_seconds: float = 3,
    max_observation_age_seconds: float = 15,
    concurrency: int = 3,
) -> dict[str, DependencyObservation]:
    if not 0.05 <= timeout_seconds <= 30:
        raise OperationalInvariantError("probe timeout must be within 0.05..30 seconds")
    if not 0 < max_observation_age_seconds <= 300:
        raise OperationalInvariantError(
            "probe observation age must be within 0..300 seconds"
        )
    if not 1 <= concurrency <= len(REQUIRED_DEPENDENCIES):
        raise OperationalInvariantError(
            "probe concurrency must be within the dependency count"
        )
    unknown = set(probes) - set(REQUIRED_DEPENDENCIES)
    if unknown:
        raise OperationalInvariantError("unknown operational dependency probe")

    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(dependency: str) -> tuple[str, DependencyObservation]:
        probe = probes.get(dependency)
        if probe is None:
            return dependency, _blocked_observation(
                dependency,
                reason_code="PROBE_UNCONFIGURED",
                observed_at=observed_at,
            )
        started = time.perf_counter()
        try:
            async with semaphore:
                observation = await asyncio.wait_for(
                    probe.probe(observed_at=observed_at),
                    timeout=timeout_seconds,
                )
        except TimeoutError:
            return dependency, _blocked_observation(
                dependency,
                reason_code="PROBE_TIMEOUT",
                observed_at=observed_at,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception:  # noqa: BLE001 - dependency details must remain ephemeral
            return dependency, _blocked_observation(
                dependency,
                reason_code="PROBE_FAILED",
                observed_at=observed_at,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        probe_time = observation.observed_at
        if probe_time.tzinfo is None:
            probe_time = probe_time.replace(tzinfo=UTC)
        else:
            probe_time = probe_time.astimezone(UTC)
        now = observed_at.replace(tzinfo=UTC) if observed_at.tzinfo is None else observed_at.astimezone(UTC)
        if (
            probe_time > now + timedelta(seconds=5)
            or now - probe_time > timedelta(seconds=max_observation_age_seconds)
        ):
            observation = _blocked_observation(
                dependency,
                reason_code="PROBE_OBSERVATION_STALE",
                observed_at=probe_time,
                latency_ms=observation.latency_ms,
            )
        return dependency, observation

    results = await asyncio.gather(*(run_one(name) for name in REQUIRED_DEPENDENCIES))
    return dict(results)


async def run_operational_readiness_probes(
    db: AsyncSession,
    command: RunOperationalProbes,
    *,
    probes: Mapping[str, DependencyProbe],
):
    observations = await collect_dependency_observations(
        probes,
        observed_at=command.observed_at,
        timeout_seconds=command.timeout_seconds,
        max_observation_age_seconds=command.max_observation_age_seconds,
        concurrency=command.concurrency,
    )
    return await assess_operational_readiness(
        db,
        AssessOperationalReadiness(
            org_id=command.org_id,
            target_id=command.target_id,
            dependency_states=observations,
            build_ref=command.build_ref,
            schema_version=command.schema_version,
            observed_at=command.observed_at,
            ttl_seconds=command.ttl_seconds,
        ),
    )


async def run_operational_probe_batch(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    build_ref: str,
    schema_version: str,
    probes: Mapping[str, DependencyProbe] | None = None,
    now: datetime | None = None,
    batch_size: int = 100,
    target_concurrency: int = 2,
    probe_concurrency: int = 3,
    timeout_seconds: float = 3,
    assessment_ttl_seconds: int = 60,
    refresh_before_seconds: int = 15,
) -> OperationalProbeBatchResult:
    if not 1 <= batch_size <= 1_000:
        raise OperationalInvariantError("probe batch size must be within 1..1000")
    if not 1 <= target_concurrency <= 8:
        raise OperationalInvariantError("target concurrency must be within 1..8")
    if not 1 <= refresh_before_seconds < assessment_ttl_seconds <= 300:
        raise OperationalInvariantError(
            "assessment refresh and TTL must satisfy 1 <= refresh < TTL <= 300"
        )
    if not build_ref.strip() or len(build_ref) > 128:
        raise OperationalInvariantError("build ref must contain 1..128 characters")
    if not schema_version.strip() or len(schema_version) > 64:
        raise OperationalInvariantError("schema version must contain 1..64 characters")
    observed_at = now or datetime.now(UTC)
    active_probes = probes if probes is not None else _configured_probes

    table = OperationalTarget.__table__
    rank = func.row_number().over(
        partition_by=table.c.org_id,
        order_by=(table.c.signed_at.desc(), table.c.id.desc()),
    ).label("target_rank")
    ranked = (
        select(table.c.id, table.c.org_id, rank)
        .where(table.c.status == "signed")
        .subquery()
    )
    async with session_factory() as discovery_db:
        rows = list(
            (
                await discovery_db.execute(
                    select(ranked.c.id, ranked.c.org_id)
                    .where(ranked.c.target_rank == 1)
                    .order_by(ranked.c.org_id)
                    .limit(batch_size)
                )
            ).all()
        )

    semaphore = asyncio.Semaphore(target_concurrency)

    async def assess_target(target_id: str, org_id: str) -> str:
        async with semaphore:
            with tenant_context(org_id):
                async with session_factory() as db:
                    fresh = await db.scalar(
                        select(OperationalReadinessAssessment.id)
                        .where(
                            OperationalReadinessAssessment.org_id == org_id,
                            OperationalReadinessAssessment.target_id == target_id,
                            OperationalReadinessAssessment.valid_until
                            > observed_at
                            + timedelta(seconds=refresh_before_seconds),
                        )
                        .order_by(
                            OperationalReadinessAssessment.observed_at.desc()
                        )
                        .limit(1)
                    )
                    if fresh is not None:
                        return "skipped"
                    assessment = await run_operational_readiness_probes(
                        db,
                        RunOperationalProbes(
                            org_id=org_id,
                            target_id=target_id,
                            build_ref=build_ref.strip(),
                            schema_version=schema_version.strip(),
                            observed_at=observed_at,
                            ttl_seconds=assessment_ttl_seconds,
                            timeout_seconds=timeout_seconds,
                            concurrency=probe_concurrency,
                        ),
                        probes=active_probes,
                    )
                    await db.commit()
                    return assessment.status

    outcomes = await asyncio.gather(
        *(assess_target(str(row.id), str(row.org_id)) for row in rows)
    )
    return OperationalProbeBatchResult(
        discovered=len(rows),
        assessed=len(outcomes) - outcomes.count("skipped"),
        ready=outcomes.count("ready"),
        blocked=outcomes.count("blocked"),
        skipped_fresh=outcomes.count("skipped"),
    )


def operational_probe_interval_seconds() -> float:
    raw = os.getenv("AI_DEVICE_LAB_OPERATIONAL_PROBE_INTERVAL_SECONDS", "30")
    try:
        return max(5.0, min(300.0, float(raw)))
    except ValueError:
        return 30.0


async def operational_probe_loop() -> None:
    """Refresh assessments only when probes and release identity are configured."""
    from db import database
    from web.metrics import (
        ai_device_lab_operational_probe_assessments_total,
        ai_device_lab_operational_probe_duration_seconds,
        ai_device_lab_operational_probe_runs_total,
    )

    interval = operational_probe_interval_seconds()
    while True:
        started = time.perf_counter()
        status = "success"
        try:
            build_ref = os.getenv("AI_DEVICE_LAB_BUILD_REF", "").strip()
            schema_version = os.getenv("AI_DEVICE_LAB_SCHEMA_VERSION", "").strip()
            if database.schema_init_ok is False:
                status = "schema_unavailable"
            elif not _configured_probes:
                status = "probes_unconfigured"
            elif not build_ref or not schema_version:
                status = "release_identity_unconfigured"
            else:
                result = await run_operational_probe_batch(
                    database.AsyncSessionLocal,
                    build_ref=build_ref,
                    schema_version=schema_version,
                )
                for outcome, count in (
                    ("ready", result.ready),
                    ("blocked", result.blocked),
                    ("skipped_fresh", result.skipped_fresh),
                ):
                    if count:
                        ai_device_lab_operational_probe_assessments_total.labels(
                            outcome=outcome
                        ).inc(count)
        except asyncio.CancelledError:
            raise
        except Exception:
            status = "error"
            log.exception("AI Device Lab operational dependency probe pass failed")
        finally:
            ai_device_lab_operational_probe_runs_total.labels(status=status).inc()
            ai_device_lab_operational_probe_duration_seconds.observe(
                time.perf_counter() - started
            )
        await asyncio.sleep(interval)
