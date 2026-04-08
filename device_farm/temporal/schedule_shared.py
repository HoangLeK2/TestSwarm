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


@dataclass
class ScheduleDispatchResult:
    """Result returned by the dispatch activity."""
    run_id: str
    devices_dispatched: int = 0
    task_ids: list[str] = field(default_factory=list)
    workflow_ids: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ScheduleRunOutput:
    """Final output of ScheduleRunWorkflow."""
    schedule_id: str
    run_id: str
    status: str  # completed | failed | partial
    devices_dispatched: int = 0
    error: str | None = None
