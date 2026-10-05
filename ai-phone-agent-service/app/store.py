from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from threading import RLock
from uuid import uuid4

from fastapi import HTTPException, status

from .contracts import (
    PROMPT_POLICY_VERSION,
    SCHEMA_VERSION,
    ActionResultRequest,
    Budget,
    CancelResponse,
    ObservationRequest,
    ObservationResponse,
    PlanRequest,
    PlanResponse,
    PlanStatus,
    SessionRequest,
    SessionResponse,
    SessionStatus,
    utc_now,
)
from .planner import PlannerPort


def request_hash(value: object) -> str:
    return sha256(repr(value).encode("utf-8")).hexdigest()


@dataclass
class SessionRecord:
    response: SessionResponse
    org_id: str
    app_package: str
    allowed_operations: set[str]
    step_index: int = 0
    action_results: list[ActionResultRequest] = field(default_factory=list)


class AgentStore:
    def __init__(self, planner: PlannerPort):
        self._planner = planner
        self._lock = RLock()
        self._plans_by_idempotency: dict[tuple[str, str], PlanResponse] = {}
        self._plans: dict[str, PlanResponse] = {}
        self._sessions_by_idempotency: dict[tuple[str, str], SessionRecord] = {}
        self._sessions: dict[str, SessionRecord] = {}

    @property
    def planner(self) -> PlannerPort:
        return self._planner

    def create_plan(self, request: PlanRequest) -> PlanResponse:
        key = (request.org_id, request.idempotency_key)
        with self._lock:
            existing = self._plans_by_idempotency.get(key)
            if existing is not None:
                return existing

            now = utc_now()
            draft = self._planner.build_plan(request)
            response = PlanResponse(
                schema_version=SCHEMA_VERSION,
                job_id=f"plan_{uuid4().hex}",
                status=PlanStatus.succeeded,
                correlation_id=request.correlation_id,
                model=self._planner.model_name,
                model_revision=self._planner.model_revision,
                prompt_policy_version=PROMPT_POLICY_VERSION,
                input_hash=request_hash(request.model_dump(mode="json")),
                draft=draft,
                reason_code="plan.generated",
                created_at=now,
                updated_at=now,
            )
            self._plans_by_idempotency[key] = response
            self._plans[response.job_id] = response
            return response

    def get_plan(self, job_id: str) -> PlanResponse:
        with self._lock:
            plan = self._plans.get(job_id)
            if plan is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
            return plan

    def create_session(self, request: SessionRequest) -> SessionResponse:
        key = (request.org_id, request.idempotency_key)
        with self._lock:
            existing = self._sessions_by_idempotency.get(key)
            if existing is not None:
                return existing.response

            now = utc_now()
            response = SessionResponse(
                schema_version=SCHEMA_VERSION,
                session_id=f"sess_{uuid4().hex}",
                status=SessionStatus.active,
                correlation_id=request.correlation_id,
                model=self._planner.model_name,
                model_revision=self._planner.model_revision,
                prompt_policy_version=PROMPT_POLICY_VERSION,
                budget=request.budget,
                created_at=now,
                updated_at=now,
            )
            record = SessionRecord(
                response=response,
                org_id=request.org_id,
                app_package=request.app_package,
                allowed_operations=set(request.allowed_operations),
            )
            self._sessions_by_idempotency[key] = record
            self._sessions[response.session_id] = record
            return response

    def observe(self, session_id: str, request: ObservationRequest) -> ObservationResponse:
        with self._lock:
            record = self._get_active_session(session_id)
            if request.app_package != record.app_package:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Observation package does not match session package",
                )
            action = self._planner.propose_action(
                request,
                record.allowed_operations,
                record.step_index,
            )
            if action.operation not in record.allowed_operations:
                action = action.model_copy(
                    update={
                        "operation": "finish",
                        "params": {"outcome": "policy_denied"},
                        "confidence": 0.0,
                        "reason_code": "proposal.denied_by_allowed_operations",
                    }
                )
            record.step_index += 1
            return ObservationResponse(
                schema_version=SCHEMA_VERSION,
                session_id=session_id,
                correlation_id=request.correlation_id,
                model=self._planner.model_name,
                model_revision=self._planner.model_revision,
                prompt_policy_version=PROMPT_POLICY_VERSION,
                input_hash=request_hash(request.model_dump(mode="json")),
                action=action,
            )

    def record_action_result(self, session_id: str, request: ActionResultRequest) -> SessionResponse:
        with self._lock:
            record = self._get_active_session(session_id)
            record.action_results.append(request)
            now = utc_now()
            status_value = SessionStatus.finished if request.status == "succeeded" and request.action_id.endswith("finish") else record.response.status
            record.response = record.response.model_copy(update={"status": status_value, "updated_at": now})
            return record.response

    def cancel_session(self, session_id: str, correlation_id: str) -> CancelResponse:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
            now = utc_now()
            record.response = record.response.model_copy(
                update={"status": SessionStatus.canceled, "updated_at": now}
            )
            return CancelResponse(
                schema_version=SCHEMA_VERSION,
                session_id=session_id,
                status=SessionStatus.canceled,
                correlation_id=correlation_id,
                updated_at=now,
            )

    def metrics_text(self) -> str:
        with self._lock:
            active_sessions = sum(1 for item in self._sessions.values() if item.response.status == SessionStatus.active)
            return "\n".join(
                [
                    "# HELP ai_phone_agent_plans_total Plans created in memory.",
                    "# TYPE ai_phone_agent_plans_total gauge",
                    f"ai_phone_agent_plans_total {len(self._plans)}",
                    "# HELP ai_phone_agent_sessions_active Active sessions in memory.",
                    "# TYPE ai_phone_agent_sessions_active gauge",
                    f"ai_phone_agent_sessions_active {active_sessions}",
                    "",
                ]
            )

    def _get_active_session(self, session_id: str) -> SessionRecord:
        record = self._sessions.get(session_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        if record.response.status != SessionStatus.active:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is not active")
        if record.step_index >= record.response.budget.max_steps:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Step budget exhausted")
        return record
