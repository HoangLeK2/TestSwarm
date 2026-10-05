
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from temporalio import workflow


MAX_NESTING_DEPTH = 10
TASK_QUEUE_NAME = "device-scenario"

# Short control-plane activities live on their own queue so they never wait
# behind long device work. Measured on the shared queue: with 140 slots busy, a
# 34ms activity waited 20.5s to start — and finalize_campaign, the activity that
# releases the phone, is one of those. Workflows are not split: workflow tasks
# use a separate slot pool and were never starved.
#
# Workflow code cannot read config, so the name is a constant here;
# TemporalConfig.control_task_queue mirrors it for the worker side.
CONTROL_TASK_QUEUE_NAME = "device-control"

# Changing an activity's task queue changes the command a workflow emits, so an
# in-flight workflow replaying old history would fail the determinism check.
# The patch keeps old runs scheduling on their original queue while new runs use
# the control queue; device workers keep these activities registered so the old
# runs still find someone to execute them.
CONTROL_QUEUE_PATCH = "control-task-queue-v1"


def control_task_queue() -> str | None:
    """Task queue for short control-plane activities, or None before the patch.

    None is what temporalio already means by "the workflow's own task queue", so
    unpatched histories behave exactly as they did.

    The temporalio import is at module scope on purpose. Importing inside this
    function crashed the claim keepalive with "coroutine ignored GeneratorExit":
    it is called from a coroutine that gets cancelled, and the import machinery
    swallows the GeneratorExit that cancellation raises.
    """
    return CONTROL_TASK_QUEUE_NAME if workflow.patched(CONTROL_QUEUE_PATCH) else None


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
    # Execution coordinator ID — links to executions table
    # Legacy: run_id is kept as alias for backward compat with in-flight workflows
    run_id: str | None = None
    execution_id: str | None = None
    start_step: int = 0


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
    run_id: str | None = None  # Legacy alias for execution_id
    execution_id: str | None = None
    # Accumulates step_results across continue_as_new boundaries so retry/history-reset
    # workflows still return the full result set to the parent ScenarioWorkflow.
    accumulated_results: list[dict[str, Any]] = field(default_factory=list)
    # Steps already flushed to execution_steps and dropped from
    # accumulated_results, so counters stay right without carrying the payload.
    checkpointed_steps: int = 0
    start_step: int = 0


@dataclass
class StepResult:
    index: int
    step_type: str
    ok: bool
    # Optional so Temporal can deserialize legacy payloads that have message=null
    message: str | None = ""
    details: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


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
    execution_id: str | None = None
    campaign_id: str | None = None
    depth: int = 0
    # Shared runtime context (posts, comment parent anchors, loop vars, …).
    context: dict[str, Any] = field(default_factory=dict)
    # Temporal scheduling metadata. Optional for backwards compatibility with
    # older workflow histories and direct unit tests.
    activity_id: str | None = None
    activity_attempt: int = 1
    side_effect_class: str | None = None


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
    run_id: str | None = None  # Legacy alias for execution_id
    execution_id: str | None = None
    campaign_id: str | None = None
    depth: int = 0
    context: dict[str, Any] = field(default_factory=dict)
    activity_id: str | None = None
    step_activity_ids: list[str] = field(default_factory=list)
    side_effect_class: str | None = None


@dataclass
class DeviceActionBatchResult:
    results: list[dict[str, Any]] = field(default_factory=list)   # per-step StepResult dicts
    first_failure_index: int = -1   # index into results of first failed step, -1 if all ok
    paused_mid_batch: bool = False
    cancelled_mid_batch: bool = False
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ElementCheckInput:
    device_serial: str
    by: str
    value: str
    timeout: float = 3.0
    execution_id: str | None = None
    campaign_id: str | None = None


@dataclass
class ElementCheckResult:
    found: bool
    message: str | None = ""


@dataclass
class ConditionCheckInput:
    device_serial: str
    condition: dict[str, Any]
    runtime_vars: dict[str, Any] = field(default_factory=dict)
    execution_id: str | None = None
    campaign_id: str | None = None


class WorkflowStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    PAUSED_ON_ERROR = "paused_on_error"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkflowProgress:
    status: str = WorkflowStatus.RUNNING.value
    current_step: int = 0
    total_steps: int = 0
    current_step_type: str = ""
    current_step_id: str | None = None
    current_step_path: str | None = None
    current_loop_iter: int | None = None
    current_activity_id: str | None = None
    current_step_activity_id: str | None = None
    current_phase: str | None = None
    side_effect_class: str | None = None
    activity_attempt: int = 0
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
    execution_id: str | None = None
    campaign_id: str | None = None


@dataclass
class ExtractInput:
    """Input for execute_extract activity."""
    device_serial: str
    step: dict[str, Any]
    step_index: int = 0
    # Current context — extract mutates posts / text_nodes / _no_new_streak
    context: dict[str, Any] = field(default_factory=dict)
    scenario_config: dict[str, Any] = field(default_factory=dict)
    campaign_id: str | None = None
    run_id: str | None = None  # Legacy alias for execution_id
    execution_id: str | None = None
    user_id: str | None = None


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
    run_id: str | None = None  # Legacy alias for execution_id
    execution_id: str | None = None
    account_id: str | None = None
    user_id: str | None = None
    campaign_vars: dict[str, Any] = field(default_factory=dict)
