"""
temporal/schedule_shared.py — Shared dataclasses for schedule workflow I/O (DF-008).

All types must be JSON-serializable (Temporal payload converter requirement).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScheduleRunInput:
    """Input to ScheduleRunWorkflow — passed when Temporal Schedule fires."""
    schedule_id: str
    run_id: str | None = None


@dataclass
class ScheduleDispatchResult:
    """Result returned by the dispatch activity."""
    run_id: str
    devices_dispatched: int = 0
    devices_succeeded: int = 0
    devices_failed: int = 0
    task_ids: list[str] = field(default_factory=list)
    workflow_ids: list[str] = field(default_factory=list)
    error: str | None = None

    def __post_init__(self) -> None:
        if (
            self.error is None
            and self.devices_dispatched > 0
            and self.devices_succeeded == 0
            and self.devices_failed == 0
        ):
            self.devices_succeeded = self.devices_dispatched


@dataclass
class ScheduleRunOutput:
    """Final output of ScheduleRunWorkflow."""
    schedule_id: str
    run_id: str
    status: str  # completed | failed | partial
    devices_dispatched: int = 0
    devices_succeeded: int = 0
    devices_failed: int = 0
    error: str | None = None
