import type { ExecutionEventOut } from '../../device-farm/services/generated/DeviceFarmApi';
import type { ExecutionOut, StepLogEntry, WorkflowProgress } from '../types';

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
  const byIndex = new Map<number, StepLogEntry>();

  for (const ev of events) {
    const p = (ev.payload ?? {}) as Record<string, unknown>;
    const idx = Number(p.step_index ?? 0);

    if (ev.event_type === 'step.completed' || ev.event_type === 'step.failed') {
      const stepType = String(p.step_type ?? '');
      const ok = ev.event_type === 'step.completed';
      byIndex.set(idx, {
        index: idx,
        type: stepType,
        step_type: stepType,
        ok,
        message: String(p.message ?? p.reason_code ?? '') || null,
        depth: 0,
        output: typeof p.output === 'string' ? p.output : null,
        exit_code: typeof p.exit_code === 'number' ? p.exit_code : null,
        save_as: typeof p.save_as === 'string' ? p.save_as : null,
        output_truncated: Boolean(p.output_truncated)
      });
    }
  }

  return Array.from(byIndex.entries())
    .sort(([a], [b]) => a - b)
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
