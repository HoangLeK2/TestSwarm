"""Execution domain event type constants (DF-T-04-013)."""
from __future__ import annotations

SCHEMA_VERSION = "1"
BROKER_TOPIC = "df.execution.events.v1"

EXECUTION_CREATED = "execution.created"
EXECUTION_STARTED = "execution.started"
EXECUTION_COMPLETED = "execution.completed"
EXECUTION_FAILED = "execution.failed"
EXECUTION_CANCELLED = "execution.cancelled"
EXECUTION_PAUSED = "execution.paused"
EXECUTION_RESUMED = "execution.resumed"
EXECUTION_DLQ_OPENED = "execution.dlq.opened"
EXECUTION_DLQ_REPLAYED = "execution.dlq.replayed"
EXECUTION_DLQ_CLOSED = "execution.dlq.closed"

STEP_STARTED = "step.started"
STEP_COMPLETED = "step.completed"
STEP_FAILED = "step.failed"
STEP_RETRIED = "step.retried"

TEMPORAL_ACTIVITY_SCHEDULED = "temporal.activity.scheduled"
TEMPORAL_ACTIVITY_RETRYING = "temporal.activity.retrying"
TEMPORAL_ACTIVITY_COMPLETED = "temporal.activity.completed"
TEMPORAL_ACTIVITY_FAILED = "temporal.activity.failed"
TEMPORAL_ACTIVITY_STALLED = "temporal.activity.stalled"

INCIDENT_DETECTED = "incident.detected"
INCIDENT_RECOVERY_STARTED = "incident.recovery.started"
INCIDENT_RECOVERY_COMPLETED = "incident.recovery.completed"
INCIDENT_RESOLVED = "incident.resolved"
INCIDENT_FAILED = "incident.failed"

EXECUTION_LIFECYCLE_EVENTS = frozenset({
    EXECUTION_CREATED,
    EXECUTION_STARTED,
    EXECUTION_COMPLETED,
    EXECUTION_FAILED,
    EXECUTION_CANCELLED,
    EXECUTION_PAUSED,
    EXECUTION_RESUMED,
    EXECUTION_DLQ_OPENED,
    EXECUTION_DLQ_REPLAYED,
    EXECUTION_DLQ_CLOSED,
})

STEP_EVENTS = frozenset({
    STEP_STARTED,
    STEP_COMPLETED,
    STEP_FAILED,
    STEP_RETRIED,
})

TEMPORAL_ACTIVITY_EVENTS = frozenset({
    TEMPORAL_ACTIVITY_SCHEDULED,
    TEMPORAL_ACTIVITY_RETRYING,
    TEMPORAL_ACTIVITY_COMPLETED,
    TEMPORAL_ACTIVITY_FAILED,
    TEMPORAL_ACTIVITY_STALLED,
})

INCIDENT_EVENTS = frozenset({
    INCIDENT_DETECTED,
    INCIDENT_RECOVERY_STARTED,
    INCIDENT_RECOVERY_COMPLETED,
    INCIDENT_RESOLVED,
    INCIDENT_FAILED,
})

ALL_EXECUTION_EVENT_TYPES = (
    EXECUTION_LIFECYCLE_EVENTS
    | STEP_EVENTS
    | TEMPORAL_ACTIVITY_EVENTS
    | INCIDENT_EVENTS
)
