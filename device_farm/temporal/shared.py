
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


MAX_NESTING_DEPTH = 10
TASK_QUEUE_NAME = "device-scenario"


@dataclass
class ScenarioInput:
    campaign_id: str
    device_serial: str
    steps: list[dict[str, Any]]
    variables: dict[str, Any] = field(default_factory=dict)
    campaign_vars: dict[str, Any] = field(default_factory=dict)
    scenario_registry: dict[str, Any] = field(default_factory=dict)
    capture_steps: bool = False
    # Scenario-level config: visual_anchor, implicit_wait, etc.
    # Passed through to each activity so 1-step mini-scenarios inherit settings.
    scenario_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepsInput:
    device_serial: str
    steps: list[dict[str, Any]]
    variables: dict[str, Any] = field(default_factory=dict)
    campaign_vars: dict[str, Any] = field(default_factory=dict)
    scenario_registry: dict[str, Any] = field(default_factory=dict)
    depth: int = 0
    parent_runtime_vars: dict[str, Any] = field(default_factory=dict)
    # Scenario-level config forwarded from ScenarioInput
    scenario_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    index: int
    step_type: str
    ok: bool
    # Optional so Temporal can deserialize legacy payloads that have message=null
    message: str | None = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepsResult:
    success: bool
    steps_executed: int
    step_results: list[dict[str, Any]] = field(default_factory=list)
    runtime_vars: dict[str, Any] = field(default_factory=dict)
    failed_message: str | None = ""


@dataclass
class DeviceActionInput:
    device_serial: str
    step: dict[str, Any]
    step_index: int = 0
    variables: dict[str, Any] = field(default_factory=dict)
    campaign_vars: dict[str, Any] = field(default_factory=dict)
    # Scenario-level config passed through so each 1-step mini-scenario
    # inherits visual_anchor / implicit_wait / capture_steps settings.
    scenario_config: dict[str, Any] = field(default_factory=dict)
    # Scenario registry for run_scenario sub-step resolution.
    # Contains by_id, by_campaign_name, by_template_name dicts.
    scenario_registry: dict[str, Any] = field(default_factory=dict)


@dataclass
class ElementCheckInput:
    device_serial: str
    by: str
    value: str
    timeout: float = 3.0


@dataclass
class ElementCheckResult:
    found: bool
    message: str | None = ""


@dataclass
class ConditionCheckInput:
    device_serial: str
    condition: dict[str, Any]
    runtime_vars: dict[str, Any] = field(default_factory=dict)


class WorkflowStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkflowProgress:
    status: str = WorkflowStatus.RUNNING.value
    current_step: int = 0
    total_steps: int = 0
    current_step_type: str = ""
    loop_iteration: int = -1
    message: str = ""
    device_serial: str = ""
