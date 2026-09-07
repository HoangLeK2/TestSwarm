import type { StepLogEntry } from '../types';

export type ExecutionTraceSummary = {
  stepId: string | null;
  stepPath: string | null;
  loopId: string | null;
  loopIter: number | null;
  branch: string | null;
  reasonCode: string | null;
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object'
    ? (value as Record<string, unknown>)
    : {};
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function pathText(value: unknown): string | null {
  if (Array.isArray(value)) {
    const joined = value
      .map((item) => String(item ?? '').trim())
      .filter(Boolean)
      .join('.');
    return joined || null;
  }
  return text(value);
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function emptyExecutionTrace(): ExecutionTraceSummary {
  return {
    stepId: null,
    stepPath: null,
    loopId: null,
    loopIter: null,
    branch: null,
    reasonCode: null
  };
}

export function hasExecutionTrace(
  trace: Partial<ExecutionTraceSummary> | null | undefined
): boolean {
  return Boolean(
    trace?.stepId ||
      trace?.stepPath ||
      trace?.loopId ||
      trace?.loopIter != null ||
      trace?.branch ||
      trace?.reasonCode
  );
}

export function mergeExecutionTrace(
  primary: Partial<ExecutionTraceSummary> | null | undefined,
  fallback: Partial<ExecutionTraceSummary> | null | undefined
): ExecutionTraceSummary {
  return {
    stepId: primary?.stepId ?? fallback?.stepId ?? null,
    stepPath: primary?.stepPath ?? fallback?.stepPath ?? null,
    loopId: primary?.loopId ?? fallback?.loopId ?? null,
    loopIter: primary?.loopIter ?? fallback?.loopIter ?? null,
    branch: primary?.branch ?? fallback?.branch ?? null,
    reasonCode: primary?.reasonCode ?? fallback?.reasonCode ?? null
  };
}

export function executionTraceFromRecord(
  source: Record<string, unknown> | null | undefined
): ExecutionTraceSummary {
  const raw = record(source);
  const trace = record(raw.trace);
  return {
    stepId:
      text(raw.current_step_id) ?? text(raw.step_id) ?? text(trace.step_id),
    stepPath:
      pathText(raw.current_step_path) ??
      pathText(raw.step_path) ??
      pathText(raw.path_key) ??
      pathText(raw.path) ??
      pathText(trace.step_path) ??
      pathText(trace.path_key) ??
      pathText(trace.path),
    loopId: text(raw.loop_id) ?? text(trace.loop_id),
    loopIter:
      numberValue(raw.current_loop_iter) ??
      numberValue(raw.loop_iter) ??
      numberValue(raw.loop_iteration) ??
      numberValue(trace.loop_iter),
    branch: text(raw.branch) ?? text(trace.branch),
    reasonCode: text(raw.reason_code) ?? text(trace.reason_code)
  };
}

export function executionTraceFromLog(
  log: StepLogEntry | null | undefined
): ExecutionTraceSummary {
  if (!log) return emptyExecutionTrace();
  const raw = log as StepLogEntry & Record<string, unknown>;
  const details = record(log.details);
  const trace = record(log.trace);
  return {
    stepId: text(raw.step_id) ?? text(details.step_id) ?? text(trace.step_id),
    stepPath:
      pathText(raw.step_path) ??
      pathText(raw.path_key) ??
      pathText(raw.path) ??
      pathText(details.step_path) ??
      pathText(details.path_key) ??
      pathText(details.path) ??
      pathText(trace.step_path) ??
      pathText(trace.path_key) ??
      pathText(trace.path),
    loopId: text(raw.loop_id) ?? text(details.loop_id) ?? text(trace.loop_id),
    loopIter:
      numberValue(raw.current_loop_iter) ??
      numberValue(raw.loop_iter) ??
      numberValue(details.current_loop_iter) ??
      numberValue(details.loop_iter) ??
      numberValue(details.loop_iteration) ??
      numberValue(trace.loop_iter),
    branch: text(raw.branch) ?? text(details.branch) ?? text(trace.branch),
    reasonCode:
      text(raw.reason_code) ??
      text(details.reason_code) ??
      text(trace.reason_code)
  };
}

export function normalizeTracePathForMatch(
  value: string | null
): string | null {
  return value?.replace(/#\d+(?=\/|$)/g, '') ?? null;
}
