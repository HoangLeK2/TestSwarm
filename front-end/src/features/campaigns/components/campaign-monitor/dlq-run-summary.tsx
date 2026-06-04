import type { ExecutionOut } from '../../types';

export function findExecutionForDlq(
  executions: ExecutionOut[],
  executionId: string
): ExecutionOut | undefined {
  return executions.find((ex) => ex.id === executionId);
}

const EXEC_STATUS_KEYS = [
  'failed',
  'completed',
  'running',
  'pending',
  'cancelled',
  'paused'
] as const;

const RUN_TYPE_KEYS = ['campaign', 'preview', 'manual'] as const;

export function executionStatusLabel(
  status: string,
  t: (key: string) => string
): string {
  const normalized = status.toLowerCase().replace(/-/g, '_');
  if ((EXEC_STATUS_KEYS as readonly string[]).includes(normalized)) {
    return t(`monitorDlqExecStatus_${normalized}`);
  }
  return status;
}

export function executionRunTypeLabel(
  runType: string,
  t: (key: string) => string
): string {
  const normalized = runType.toLowerCase().replace(/-/g, '_');
  if ((RUN_TYPE_KEYS as readonly string[]).includes(normalized)) {
    return t(`monitorDlqRunType_${normalized}`);
  }
  return runType;
}

export function executionScenarioLabel(ex: ExecutionOut): string | null {
  const meta = (ex.meta ?? {}) as Record<string, unknown>;
  const name =
    meta.scenario_name ??
    meta.org_scenario_name ??
    meta.scenario_title ??
    meta.name;
  if (typeof name === 'string' && name.trim()) return name.trim();
  if (ex.scenario_id) return ex.scenario_id.slice(0, 8);
  return null;
}

export function formatTs(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}
