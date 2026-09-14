import type { StepLogEntry } from '@/features/campaigns/types';
import type { AccountRunEventOut, AccountRunStepOut } from '../services/api';

/**
 * Adapt a persisted execution_steps row to the shape the campaign monitor's
 * StepRow already renders.
 *
 * The live monitor reads steps off a Temporal workflow query, which disappears
 * when the workflow ages out of retention. execution_steps is the copy that
 * survives, and it is the only one a ban investigation weeks later can read —
 * but it is shaped for storage (status string, nested trace) rather than for
 * display. This is the translation, kept in one place so the row component
 * stays unaware of where its data came from.
 */

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** execution_steps.status -> the tri-state StepRow understands. */
function rowStatus(status: string): 'running' | 'completed' | 'failed' {
  if (status === 'failed' || status === 'error') return 'failed';
  if (status === 'running' || status === 'in_progress') return 'running';
  return 'completed';
}

export function runStepToLogEntry(step: AccountRunStepOut): StepLogEntry {
  const config = asRecord(step.effective_config_json);
  const trace = asRecord(config.trace);
  const action = asRecord(trace.action);
  const error = asRecord(step.error_json);
  const ok = step.status === 'passed' || step.status === 'skipped';

  return {
    index: step.step_index,
    step_id: step.step_id,
    step_type: step.step_type ?? '',
    type: step.step_type ?? undefined,
    ok,
    // The sentence the executor wrote when the step ran, when it had one. It
    // says what the account did; step.message says what the code did.
    message: asString(action.activity_summary) ?? step.message,
    depth: asNumber(trace.depth) ?? 0,
    status: rowStatus(step.status),
    step_path: asString(trace.step_path),
    loop_id: asString(trace.loop_id),
    loop_iter: asNumber(trace.loop_iter),
    branch: asString(trace.branch),
    reason_code: asString(error.reason_code),
    trace,
    details: {
      ...error,
      semantic_action: action.semantic_action ?? null,
      activity_summary: action.activity_summary ?? null,
      duration_ms: step.duration_ms,
      started_at: step.started_at,
      attempts: step.attempts_json,
      artifacts: step.artifacts_json,
      marked_ignored: step.marked_ignored,
      // Kept alongside the summary: when a step both failed and had a semantic
      // name, the reader needs the raw message to know why.
      raw_message: step.message
    }
  };
}

export function runStepsToLogEntries(
  steps: readonly AccountRunStepOut[]
): StepLogEntry[] {
  return [...steps]
    .sort((a, b) => a.step_index - b.step_index)
    .map(runStepToLogEntry);
}

/** Terminal step events only — a started/completed pair is one row, not two. */
const TERMINAL_STEP_EVENTS = new Set(['step.completed', 'step.failed']);

function eventToLogEntry(
  event: AccountRunEventOut,
  position: number
): StepLogEntry {
  const payload = asRecord(event.payload);
  const trace = asRecord(payload.trace);
  const action = asRecord(trace.action);
  const ok = event.event_type !== 'step.failed' && payload.ok !== false;

  return {
    index: asNumber(payload.step_index) ?? position,
    step_id: asString(payload.step_id) ?? event.step_id,
    step_type: asString(payload.step_type) ?? '',
    type: asString(payload.step_type) ?? undefined,
    ok,
    message: asString(action.activity_summary) ?? asString(payload.message),
    depth: asNumber(payload.depth) ?? asNumber(trace.depth) ?? 0,
    status: ok ? 'completed' : 'failed',
    step_path: asString(trace.step_path),
    loop_id: asString(trace.loop_id),
    loop_iter: asNumber(trace.loop_iter),
    branch: asString(trace.branch),
    reason_code: asString(payload.reason_code),
    trace,
    details: {
      semantic_action: action.semantic_action ?? null,
      activity_summary: action.activity_summary ?? null,
      duration_ms: payload.duration_ms ?? null,
      occurred_at: event.occurred_at,
      raw_message: payload.message ?? null,
      failure_class: payload.failure_class ?? null,
      operator_summary: payload.operator_summary ?? null
    }
  };
}

/**
 * Build the step list from execution events.
 *
 * Ordered by occurrence, not by step_index: a step inside a loop repeats the
 * same index on every iteration, so index ordering would interleave the
 * iterations into nonsense. step_path carries the iteration (`...#87`).
 */
export function runEventsToLogEntries(
  events: readonly AccountRunEventOut[]
): StepLogEntry[] {
  return events
    .filter((event) => TERMINAL_STEP_EVENTS.has(event.event_type))
    .slice()
    .sort((a, b) =>
      String(a.occurred_at ?? '').localeCompare(String(b.occurred_at ?? ''))
    )
    .map(eventToLogEntry);
}
