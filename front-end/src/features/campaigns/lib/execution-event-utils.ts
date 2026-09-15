import type { ExecutionEventOut } from '../../device-farm/services/generated/DeviceFarmApi';
import type {
  ExecutionOut,
  IncidentEvent,
  StepLogEntry,
  TemporalActivityEventSummary,
  WorkflowProgress
} from '../types';
import { mergeAppAutomationDetails } from './app-automation-monitor';
import { executionTraceFromRecord } from './execution-trace';

/** Epic 04 Temporal workflows use `exec_{execution_id}`. */
export function executionIdFromWorkflowId(
  workflowId: string
): string | undefined {
  if (workflowId.startsWith('exec_')) {
    return workflowId.slice(5) || undefined;
  }
  return undefined;
}

export function deviceSerialFromWorkflowId(
  workflowId: string
): string | undefined {
  const m = workflowId.match(/^campaign:[^:]+:device:(.+):scenario:[^:]+$/);
  return m?.[1];
}

export function resolveExecutionIdForWorkflow(
  workflowId: string,
  executions: ExecutionOut[]
): string | undefined {
  const direct = executionIdFromWorkflowId(workflowId);
  if (direct) return direct;

  const byMeta = executions.find(
    (ex) =>
      String(
        (ex.meta as Record<string, unknown> | undefined)?.workflow_id ?? ''
      ) === workflowId
  );
  if (byMeta) return byMeta.id;

  const serial = deviceSerialFromWorkflowId(workflowId);
  if (!serial) return undefined;

  const active = executions.filter((ex) =>
    ['running', 'pending', 'paused'].includes(
      String(ex.status || '').toLowerCase()
    )
  );
  const pool = active.length > 0 ? active : executions;

  return pool.find((ex) => {
    const cfg = (ex.device_config ?? {}) as Record<string, unknown>;
    const meta = (ex.meta ?? {}) as Record<string, unknown>;
    return (
      String(cfg.device_serial ?? '') === serial ||
      String(meta.device_serial ?? '') === serial
    );
  })?.id;
}

export function parseExecutionEventEnvelope(
  raw: string
): ExecutionEventOut | null {
  try {
    return JSON.parse(raw) as ExecutionEventOut;
  } catch {
    return null;
  }
}

const TEMPORAL_ACTIVITY_EVENT_STATES = {
  'temporal.activity.scheduled': 'scheduled',
  'temporal.activity.retrying': 'retrying',
  'temporal.activity.completed': 'completed',
  'temporal.activity.failed': 'failed',
  'temporal.activity.stalled': 'stalled'
} as const;

const TEMPORAL_ACTIVITY_EVENT_LIMIT = 8;

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function temporalActivityEventFromPayload(
  ev: ExecutionEventOut,
  payload: Record<string, unknown>
): TemporalActivityEventSummary | null {
  const state =
    TEMPORAL_ACTIVITY_EVENT_STATES[
      ev.event_type as keyof typeof TEMPORAL_ACTIVITY_EVENT_STATES
    ];
  if (!state) return null;

  const activityId = stringValue(payload.activity_id);
  const stepActivityId = stringValue(payload.step_activity_id);
  return {
    event_type: ev.event_type,
    state,
    activity_id: activityId,
    step_activity_id: stepActivityId,
    side_effect_class: stringValue(payload.side_effect_class),
    activity_attempt: numberValue(payload.activity_attempt),
    phase: stringValue(payload.phase),
    duration_ms: numberValue(payload.duration_ms),
    stalled_reason: stringValue(payload.stalled_reason),
    reason_code: stringValue(payload.reason_code),
    message: stringValue(payload.message),
    occurred_at: stringValue(ev.occurred_at),
    ok: typeof payload.ok === 'boolean' ? payload.ok : null,
    batch_size: numberValue(payload.batch_size)
  };
}

function appendTemporalActivityEvent(
  existing: TemporalActivityEventSummary[] | undefined,
  event: TemporalActivityEventSummary
): TemporalActivityEventSummary[] {
  const signature = `${event.event_type}:${event.activity_id ?? ''}:${
    event.step_activity_id ?? ''
  }:${event.activity_attempt ?? ''}:${event.occurred_at ?? ''}`;
  const next = [
    ...(existing ?? []).filter(
      (item) =>
        `${item.event_type}:${item.activity_id ?? ''}:${
          item.step_activity_id ?? ''
        }:${item.activity_attempt ?? ''}:${item.occurred_at ?? ''}` !==
        signature
    ),
    event
  ];
  return next.slice(-TEMPORAL_ACTIVITY_EVENT_LIMIT);
}

function statusFromTemporalActivityEvent(
  event: TemporalActivityEventSummary,
  existing?: StepLogEntry
): StepLogEntry['status'] {
  if (existing?.status === 'failed') return 'failed';
  if (existing?.status === 'completed' && event.state !== 'failed') {
    return 'completed';
  }
  if (event.state === 'completed') return 'completed';
  if (event.state === 'failed') return 'failed';
  if (event.state === 'stalled') return 'running';
  return existing?.status ?? 'running';
}

function evidenceFromPayload(
  payload: Record<string, unknown>
): Record<string, unknown> | undefined {
  return payload.evidence && typeof payload.evidence === 'object'
    ? (payload.evidence as Record<string, unknown>)
    : undefined;
}

/**
 * Fold is order-sensitive: a terminal `step.completed` followed by a late
 * activity event downgrades the row, and loop occurrences all collapse onto the
 * last one. Workflow-side telemetry ships in batches, so delivery order is not
 * timeline order — sort by the stamp the workflow put on each event.
 *
 * Only when every event carries one; without a timestamp we cannot order, and
 * guessing is worse than keeping the delivery order.
 */
function inTimelineOrder(events: ExecutionEventOut[]): ExecutionEventOut[] {
  if (!events.every((ev) => stringValue(ev.occurred_at))) return events;
  return [...events].sort((a, b) =>
    String(a.occurred_at).localeCompare(String(b.occurred_at))
  );
}

export function foldEventsToStepLog(
  events: ExecutionEventOut[]
): StepLogEntry[] {
  const byKey = new Map<string, StepLogEntry>();
  const activeByBase = new Map<string, string>();
  const occurrenceCount = new Map<string, number>();

  for (const ev of inTimelineOrder(events)) {
    const p = (ev.payload ?? {}) as Record<string, unknown>;
    const idx = Number(p.step_index ?? 0);
    const depth = typeof p.depth === 'number' ? p.depth : 0;
    const trace =
      p.trace && typeof p.trace === 'object'
        ? (p.trace as Record<string, unknown>)
        : undefined;
    const traceSummary = executionTraceFromRecord(p);
    const evidence = evidenceFromPayload(p);
    const baseKey = `${depth}:${idx}:${String(p.step_id ?? ev.step_id ?? p.step_type ?? '')}`;
    const temporalActivityEvent = temporalActivityEventFromPayload(ev, p);

    if (ev.event_type === 'execution.failed' && evidence) {
      const key = `execution:${ev.execution_id}:${ev.event_id ?? idx}`;
      const stepType = String(p.step_type ?? 'preflight');
      byKey.set(key, {
        index: idx,
        occurrence_key: key,
        step_id:
          typeof p.step_id === 'string'
            ? p.step_id
            : (ev.step_id ?? 'execution_failed'),
        type: stepType,
        step_type: stepType,
        ok: false,
        message: String(p.message ?? p.reason_code ?? '') || null,
        depth,
        status: 'failed',
        step_path:
          traceSummary.stepPath ??
          (typeof evidence.step_path === 'string' ? evidence.step_path : null),
        loop_id: traceSummary.loopId,
        loop_iter: traceSummary.loopIter,
        branch: traceSummary.branch,
        reason_code:
          traceSummary.reasonCode ??
          (typeof evidence.reason_code === 'string'
            ? evidence.reason_code
            : null),
        evidence,
        details: p,
        trace,
        temporal_activity_events: undefined
      });
    }

    if (ev.event_type === 'step.started') {
      const occurrence = (occurrenceCount.get(baseKey) ?? 0) + 1;
      occurrenceCount.set(baseKey, occurrence);
      const key = `${baseKey}:${occurrence}`;
      activeByBase.set(baseKey, key);
      const stepType = String(p.step_type ?? '');
      const existing = byKey.get(key);
      byKey.set(key, {
        index: idx,
        occurrence_key: key,
        step_id:
          typeof p.step_id === 'string'
            ? p.step_id
            : (ev.step_id ?? existing?.step_id),
        type: stepType,
        step_type: stepType,
        ok: true,
        message: String(p.message ?? '') || null,
        depth,
        status: 'running',
        step_path: traceSummary.stepPath ?? existing?.step_path,
        loop_id: traceSummary.loopId ?? existing?.loop_id,
        loop_iter: traceSummary.loopIter ?? existing?.loop_iter,
        branch: traceSummary.branch ?? existing?.branch,
        reason_code: traceSummary.reasonCode ?? existing?.reason_code,
        evidence: evidence ?? existing?.evidence,
        trace: trace ?? existing?.trace,
        incidents: existing?.incidents,
        temporal_activity_events: existing?.temporal_activity_events
      });
    }

    if (ev.event_type === 'step.completed' || ev.event_type === 'step.failed') {
      let key = activeByBase.get(baseKey);
      if (!key) {
        const occurrence = (occurrenceCount.get(baseKey) ?? 0) + 1;
        occurrenceCount.set(baseKey, occurrence);
        key = `${baseKey}:${occurrence}`;
      }
      const stepType = String(p.step_type ?? '');
      const existing = byKey.get(key);
      const ok = ev.event_type === 'step.completed';
      byKey.set(key, {
        index: idx,
        occurrence_key: key,
        step_id:
          typeof p.step_id === 'string'
            ? p.step_id
            : (ev.step_id ?? existing?.step_id),
        type: stepType,
        step_type: stepType,
        ok,
        message: String(p.message ?? p.reason_code ?? '') || null,
        depth,
        status: ok ? 'completed' : 'failed',
        output: typeof p.output === 'string' ? p.output : null,
        exit_code: typeof p.exit_code === 'number' ? p.exit_code : null,
        save_as: typeof p.save_as === 'string' ? p.save_as : null,
        output_truncated: Boolean(p.output_truncated),
        step_path: traceSummary.stepPath ?? existing?.step_path,
        loop_id: traceSummary.loopId ?? existing?.loop_id,
        loop_iter: traceSummary.loopIter ?? existing?.loop_iter,
        branch: traceSummary.branch ?? existing?.branch,
        reason_code: traceSummary.reasonCode ?? existing?.reason_code,
        evidence: evidence ?? existing?.evidence,
        details: {
          ...p,
          ...(mergeAppAutomationDetails(undefined, p) ?? {})
        },
        trace: trace ?? existing?.trace,
        incidents: existing?.incidents,
        temporal_activity_events: existing?.temporal_activity_events
      });
      activeByBase.delete(baseKey);
    }

    if (ev.event_type.startsWith('incident.')) {
      const key =
        activeByBase.get(baseKey) ??
        `${baseKey}:${occurrenceCount.get(baseKey) ?? 1}`;
      const stepType = String(p.step_type ?? '');
      const existing = byKey.get(key);
      const incident: IncidentEvent = {
        event_type: ev.event_type,
        incident_type:
          typeof p.incident_type === 'string' ? p.incident_type : undefined,
        outcome: typeof p.outcome === 'string' ? p.outcome : undefined,
        message: typeof p.message === 'string' ? p.message : null,
        attempt: typeof p.attempt === 'number' ? p.attempt : null,
        scenario_id: typeof p.scenario_id === 'string' ? p.scenario_id : null,
        recovery_scenario_id:
          typeof p.recovery_scenario_id === 'string'
            ? p.recovery_scenario_id
            : null,
        recovery_scenario_name:
          typeof p.recovery_scenario_name === 'string'
            ? p.recovery_scenario_name
            : null,
        incident_key:
          typeof p.incident_key === 'string' ? p.incident_key : null,
        rule_id: typeof p.rule_id === 'string' ? p.rule_id : null,
        matched_rule:
          typeof p.matched_rule === 'boolean' ? p.matched_rule : undefined,
        confidence: typeof p.confidence === 'number' ? p.confidence : null
      };

      byKey.set(key, {
        index: idx,
        occurrence_key: key,
        step_id:
          existing?.step_id ??
          (typeof p.step_id === 'string' ? p.step_id : ev.step_id),
        type: existing?.type ?? stepType,
        step_type: existing?.step_type ?? stepType,
        ok: existing?.ok ?? true,
        message: existing?.message ?? null,
        depth: existing?.depth ?? 0,
        status: existing?.status,
        output: existing?.output,
        exit_code: existing?.exit_code,
        save_as: existing?.save_as,
        output_truncated: existing?.output_truncated,
        step_path: traceSummary.stepPath ?? existing?.step_path,
        loop_id: traceSummary.loopId ?? existing?.loop_id,
        loop_iter: traceSummary.loopIter ?? existing?.loop_iter,
        branch: traceSummary.branch ?? existing?.branch,
        reason_code: traceSummary.reasonCode ?? existing?.reason_code,
        evidence: evidence ?? existing?.evidence,
        details: existing?.details,
        trace: trace ?? existing?.trace,
        incidents: [...(existing?.incidents ?? []), incident],
        temporal_activity_events: existing?.temporal_activity_events
      });
    }

    if (temporalActivityEvent) {
      const key =
        activeByBase.get(baseKey) ??
        `${baseKey}:${occurrenceCount.get(baseKey) ?? 1}`;
      const stepType = String(p.step_type ?? '');
      const existing = byKey.get(key);
      const status = statusFromTemporalActivityEvent(
        temporalActivityEvent,
        existing
      );
      byKey.set(key, {
        index: idx,
        occurrence_key: key,
        step_id:
          existing?.step_id ??
          (typeof p.step_id === 'string' ? p.step_id : ev.step_id),
        type: existing?.type ?? stepType,
        step_type: existing?.step_type ?? stepType,
        ok:
          status === 'failed'
            ? false
            : (existing?.ok ?? temporalActivityEvent.ok ?? true),
        message:
          existing?.message ??
          temporalActivityEvent.message ??
          stringValue(p.reason_code),
        depth: existing?.depth ?? depth,
        status,
        output: existing?.output,
        exit_code: existing?.exit_code,
        save_as: existing?.save_as,
        output_truncated: existing?.output_truncated,
        // The row's own step.* events know its full path; an activity event only
        // carries the batch prefix (`.../loop#3`, no step segment) and the next
        // iteration's `scheduled` shares a timestamp with this one's `completed`.
        // Letting it win re-stamped a finished step into the following round.
        step_path: existing?.step_path ?? traceSummary.stepPath,
        loop_id: existing?.loop_id ?? traceSummary.loopId,
        loop_iter: existing?.loop_iter ?? traceSummary.loopIter,
        branch: existing?.branch ?? traceSummary.branch,
        reason_code:
          traceSummary.reasonCode ??
          existing?.reason_code ??
          temporalActivityEvent.reason_code,
        evidence: evidence ?? existing?.evidence,
        details: existing?.details ?? p,
        trace: trace ?? existing?.trace,
        incidents: existing?.incidents,
        temporal_activity_events: appendTemporalActivityEvent(
          existing?.temporal_activity_events,
          temporalActivityEvent
        )
      });
    }
  }

  return Array.from(byKey.entries())
    .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
    .map(([, row]) => row);
}

export function foldEventsToProgress(
  events: ExecutionEventOut[],
  workflowId: string,
  deviceSerial: string
): Partial<WorkflowProgress> | null {
  if (events.length === 0) return null;

  let currentStep = 0;
  let totalSteps = 0;
  let currentStepType = '';
  let currentStepId: string | null = null;
  let currentStepPath: string | null = null;
  let currentLoopIter: number | null = null;
  let currentReasonCode: string | null = null;
  let message = '';
  let status = 'running';

  for (const ev of events) {
    const p = (ev.payload ?? {}) as Record<string, unknown>;
    const traceSummary = executionTraceFromRecord(p);
    if (ev.event_type === 'execution.completed') status = 'completed';
    if (ev.event_type === 'execution.failed') {
      status = 'failed';
      message = String(p.message ?? p.reason_code ?? message);
      currentReasonCode = traceSummary.reasonCode ?? currentReasonCode;
    }
    if (ev.event_type === 'execution.cancelled') status = 'cancelled';

    if (ev.event_type === 'step.started') {
      const idx = Number(p.step_index ?? 0);
      currentStep = idx;
      currentStepType = String(p.step_type ?? '');
      currentStepId = traceSummary.stepId ?? ev.step_id ?? currentStepId;
      currentStepPath = traceSummary.stepPath ?? currentStepPath;
      currentLoopIter = traceSummary.loopIter ?? currentLoopIter;
      currentReasonCode = traceSummary.reasonCode ?? currentReasonCode;
      totalSteps = Math.max(totalSteps, idx + 1);
    }
    if (ev.event_type === 'step.completed' || ev.event_type === 'step.failed') {
      const idx = Number(p.step_index ?? 0);
      totalSteps = Math.max(totalSteps, idx + 1);
      currentStep = idx + 1;
      currentStepType = String(p.step_type ?? currentStepType);
      currentStepId = traceSummary.stepId ?? ev.step_id ?? currentStepId;
      currentStepPath = traceSummary.stepPath ?? currentStepPath;
      currentLoopIter = traceSummary.loopIter ?? currentLoopIter;
      currentReasonCode = traceSummary.reasonCode ?? currentReasonCode;
      if (ev.event_type === 'step.failed') {
        message = String(p.message ?? p.reason_code ?? '');
        status = 'paused_on_error';
      }
    }
    if (ev.event_type === 'step.retried') {
      const attempt = p.attempt;
      const reason = p.reason ?? p.reason_code;
      message = `retry ${attempt}: ${reason}`;
    }
  }

  return {
    workflow_id: workflowId,
    status,
    current_step: currentStep,
    total_steps: totalSteps,
    current_step_type: currentStepType,
    current_step_id: currentStepId,
    current_step_path: currentStepPath,
    current_loop_iter: currentLoopIter,
    reason_code: currentReasonCode,
    loop_iteration: currentLoopIter,
    message,
    device_serial: deviceSerial,
    error_message: status === 'paused_on_error' ? message : null
  };
}
