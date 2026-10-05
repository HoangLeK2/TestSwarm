from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from .contracts import (
    PROMPT_POLICY_VERSION,
    SCHEMA_VERSION,
    ActionResultRequest,
    ActionResultResponse,
    CancelResponse,
    HealthResponse,
    ObservationRequest,
    ObservationResponse,
    PlanRequest,
    PlanResponse,
    SessionRequest,
    SessionResponse,
)
from .planner import DeterministicPlanner
from .store import AgentStore


planner = DeterministicPlanner()
store = AgentStore(planner)

app = FastAPI(
    title="AI Phone Agent Service",
    version="0.1.0",
    description="Standalone plan/action proposal service for AI Device Lab.",
)


@app.get("/health/live", response_model=HealthResponse)
def health_live() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="ai-phone-agent-service",
        schema_version=SCHEMA_VERSION,
        planner=planner.model_name,
    )


@app.get("/health/ready", response_model=HealthResponse)
def health_ready() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="ai-phone-agent-service",
        schema_version=SCHEMA_VERSION,
        planner=planner.model_name,
    )


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return store.metrics_text()


@app.post("/v1/plans", response_model=PlanResponse)
def create_plan(request: PlanRequest) -> PlanResponse:
    return store.create_plan(request)


@app.get("/v1/plans/{job_id}", response_model=PlanResponse)
def get_plan(job_id: str) -> PlanResponse:
    return store.get_plan(job_id)


@app.post("/v1/sessions", response_model=SessionResponse)
def create_session(request: SessionRequest) -> SessionResponse:
    return store.create_session(request)


@app.post("/v1/sessions/{session_id}/observations", response_model=ObservationResponse)
def observe(session_id: str, request: ObservationRequest) -> ObservationResponse:
    return store.observe(session_id, request)


@app.post("/v1/sessions/{session_id}/action-results", response_model=ActionResultResponse)
def action_result(session_id: str, request: ActionResultRequest) -> ActionResultResponse:
    updated = store.record_action_result(session_id, request)
    return ActionResultResponse(
        schema_version=SCHEMA_VERSION,
        session_id=session_id,
        status=updated.status,
        accepted=True,
        correlation_id=request.correlation_id,
        updated_at=updated.updated_at,
    )


@app.post("/v1/sessions/{session_id}/cancel", response_model=CancelResponse)
def cancel_session(session_id: str, correlation_id: str = "cancel") -> CancelResponse:
    return store.cancel_session(session_id, correlation_id)
