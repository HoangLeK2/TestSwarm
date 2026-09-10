"""Canonical execution step reason codes."""
from __future__ import annotations

HANDLER_EXCEPTION = "handler_exception"
STUCK_SCREEN = "stuck_screen"
STALE_FRAME = "stale_frame"
CAPTURE_REQUIRED_FAILED = "capture_required_failed"
INCIDENT_RECOVERY_FAILED = "incident_recovery_failed"
NODE_CAPABILITY_PREFLIGHT_FAILED = "node_capability_preflight_failed"

LOOP_STALLED = "loop_stalled"
# The loop stopped itself because Temporal event history reached the size the
# server suggests continuing at. Distinct from LOOP_STALLED: nothing was wrong
# with the screen, the run simply ran out of history budget.
LOOP_HISTORY_LIMIT = "loop_history_limit"
LOOP_ITERATION_FAILED = "loop_iteration_failed"
LOOP_NO_NESTED_STEPS = "loop_no_nested_steps"
LOOP_INVALID_COUNT = "loop_invalid_count"
BRANCH_FAILED = "branch_failed"
CONDITION_EVAL_FAILED = "condition_eval_failed"
SUBSCENARIO_FAILED = "subscenario_failed"
