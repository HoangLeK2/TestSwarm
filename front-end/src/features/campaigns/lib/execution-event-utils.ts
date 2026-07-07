import type { ExecutionEventOut } from '../../device-farm/services/generated/DeviceFarmApi';
import type {
  ExecutionOut,
  IncidentEvent,
  StepLogEntry,
  WorkflowProgress
} from '../types';
import { mergeAppAutomationDetails } from './app-automation-monitor';

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

export function foldEventsToStepLog(
  events: ExecutionEventOut[]
): StepLogEntry[] {
  const byKey = new Map<string, StepLogEntry>();

  for (const ev of events) {
    const p = (ev.payload ?? {}) as Record<string, unknown>;
    const idx = Number(p.step_index ?? 0);
    const depth = typeof p.depth === 'number' ? p.depth : 0;
    const key = `${depth}:${idx}`;

    if (ev.event_type === 'step.started') {
      const stepType = String(p.step_type ?? '');
      const existing = byKey.get(key);
      byKey.set(key, {
        index: idx,
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
        incidents: existing?.incidents
      });
    }

    if (ev.event_type === 'step.completed' || ev.event_type === 'step.failed') {
      const stepType = String(p.step_type ?? '');
      const existing = byKey.get(key);
      const ok = ev.event_type === 'step.completed';
      byKey.set(key, {
        index: idx,
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
        details: mergeAppAutomationDetails(undefined, p),
        incidents: existing?.incidents
      });
    }

    if (ev.event_type.startsWith('incident.')) {
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
        details: existing?.details,
        incidents: [...(existing?.incidents ?? []), incident]
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
  let message = '';
  let status = 'running';

  for (const ev of events) {
    const p = (ev.payload ?? {}) as Record<string, unknown>;
    if (ev.event_type === 'execution.completed') status = 'completed';
    if (ev.event_type === 'execution.failed') status = 'failed';
    if (ev.event_type === 'execution.cancelled') status = 'cancelled';

    if (ev.event_type === 'step.started') {
      const idx = Number(p.step_index ?? 0);
      currentStep = idx;
      currentStepType = String(p.step_type ?? '');
      totalSteps = Math.max(totalSteps, idx + 1);
    }
    if (ev.event_type === 'step.completed' || ev.event_type === 'step.failed') {
      const idx = Number(p.step_index ?? 0);
      totalSteps = Math.max(totalSteps, idx + 1);
      currentStep = idx + 1;
      currentStepType = String(p.step_type ?? currentStepType);
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
    loop_iteration: null,
    message,
    device_serial: deviceSerial,
    error_message: status === 'paused_on_error' ? message : null
  };
}
