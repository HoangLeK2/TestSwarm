
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
    # Run tracking — set by campaign_dispatch when creating a CampaignRun record
    run_id: str | None = None
    # Execution coordinator ID — links to executions table (DF-011)
    execution_id: str | None = None


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
    # Shared execution context: posts, text_nodes, _no_new_streak, vars (legacy ctx)
    context: dict[str, Any] = field(default_factory=dict)
    campaign_id: str | None = None
    run_id: str | None = None
    execution_id: str | None = None


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
    # Updated execution context after steps run (posts, text_nodes, vars, etc.)
    context: dict[str, Any] = field(default_factory=dict)
    # Set True when a break_if fires — signals enclosing loop to exit early
    break_requested: bool = False


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
class DeviceActionBatchInput:
    """Batch of consecutive leaf steps executed in one activity call.

    Reduces Temporal history events: N steps → 3 events instead of 3N.
    Steps must all target the same device and share the same scenario context.
    """
    device_serial: str
    steps: list[dict[str, Any]]           # list of individual step dicts
    step_indices: list[int]               # original step indices (for logging)
    variables: dict[str, Any] = field(default_factory=dict)
    campaign_vars: dict[str, Any] = field(default_factory=dict)
    scenario_config: dict[str, Any] = field(default_factory=dict)
    scenario_registry: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceActionBatchResult:
    results: list[dict[str, Any]] = field(default_factory=list)   # per-step StepResult dicts
    first_failure_index: int = -1   # index into results of first failed step, -1 if all ok


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


# ---------------------------------------------------------------------------
# New dataclasses for legacy control flow + extraction activities
# ---------------------------------------------------------------------------

@dataclass
class LegacyConditionCheckInput:
    """Input for evaluate_legacy_condition activity.

    Supports element_exists / element_not_exists / posts_count_gte /
    no_new_posts / variable_equals conditions (the full _evaluate_condition
    set from scenario_task.py).
    """
    device_serial: str
    condition: dict[str, Any]
    runtime_vars: dict[str, Any] = field(default_factory=dict)
    # Carries posts, text_nodes, vars etc. so condition checks have full ctx
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractInput:
    """Input for execute_extract activity."""
    device_serial: str
    step: dict[str, Any]
    step_index: int = 0
    # Current context — extract mutates posts / text_nodes / _no_new_streak
    context: dict[str, Any] = field(default_factory=dict)
    scenario_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractResult:
    """Output from execute_extract activity."""
    ok: bool
    message: str
    # Updated context (posts / text_nodes / _no_new_streak merged in)
    context: dict[str, Any] = field(default_factory=dict)
    # True when stop_if_no_new triggers — tells enclosing loop to break
    break_requested: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SaveExtractionInput:
    """Input for execute_save_extraction activity."""
    device_serial: str
    step: dict[str, Any]
    step_index: int = 0
    # Context carries posts / text_nodes collected so far
    context: dict[str, Any] = field(default_factory=dict)
    campaign_id: str | None = None
    run_id: str | None = None
    execution_id: str | None = None
