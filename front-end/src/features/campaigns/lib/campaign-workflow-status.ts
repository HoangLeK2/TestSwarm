import type { ExecutionOut, WorkflowInfo } from '../types';

/** Temporal / task-queue workflow statuses that still hold device work. */
export const ACTIVE_WORKFLOW_STATUSES = new Set<string>([
  'RUNNING',
  'PAUSED',
  'paused_on_error'
]);

export const TERMINAL_WORKFLOW_STATUSES = new Set<string>([
  'COMPLETED',
  'FAILED',
  'CANCELLED',
  'TERMINATED',
  'DONE'
]);

/** Execution rows that may still be driving a device. */
export const ACTIVE_EXECUTION_STATUSES = new Set<string>([
  'running',
  'pending',
  'paused'
]);

export const TERMINAL_EXECUTION_STATUSES = new Set<string>([
  'completed',
  'failed',
  'cancelled'
]);

export function isActiveWorkflowStatus(status: string): boolean {
  return ACTIVE_WORKFLOW_STATUSES.has(status);
}

export function countActiveWorkflows(
  workflows: Pick<WorkflowInfo, 'status'>[]
): number {
  return workflows.filter((w) => isActiveWorkflowStatus(w.status)).length;
}

export function countActiveExecutions(
  executions: Pick<ExecutionOut, 'status'>[]
): number {
  return executions.filter((e) => ACTIVE_EXECUTION_STATUSES.has(e.status))
    .length;
}

export function isCampaignDrainComplete(snapshot: {
  activeWorkflows: number;
  activeExecutions: number;
}): boolean {
  return snapshot.activeWorkflows === 0 && snapshot.activeExecutions === 0;
}
