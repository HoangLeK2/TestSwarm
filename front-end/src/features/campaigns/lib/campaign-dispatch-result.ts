export type DispatchExecutionResult = {
  status?: string | null;
  failure_reason?: string | null;
  workflow_id?: string | null;
};

export type DispatchResultSummaryInput = {
  target_count?: number | null;
  executions?: DispatchExecutionResult[] | null;
};

export type DispatchResultSummary = {
  total: number;
  failed: number;
  deviceClaimFailed: number;
  allTerminal: boolean;
  allFailed: boolean;
  allFailuresAreDeviceClaim: boolean;
};

const TERMINAL_DISPATCH_STATUSES = new Set([
  'cancelled',
  'canceled',
  'completed',
  'done',
  'failed',
  'success',
  'succeeded',
  'terminated'
]);

function normalizeStatus(status: string | null | undefined) {
  return (status ?? '').trim().toLowerCase();
}

function isFailedExecution(row: DispatchExecutionResult) {
  return (
    Boolean(row.failure_reason) || normalizeStatus(row.status) === 'failed'
  );
}

function isTerminalExecution(row: DispatchExecutionResult) {
  const status = normalizeStatus(row.status);
  return TERMINAL_DISPATCH_STATUSES.has(status);
}

export function summarizeDispatchResult(
  data: DispatchResultSummaryInput | null | undefined
): DispatchResultSummary {
  const executions = data?.executions ?? [];
  const targetCount = Math.max(0, data?.target_count ?? 0);
  const total = Math.max(targetCount, executions.length);
  const failed = executions.filter(isFailedExecution).length;
  const deviceClaimFailed = executions.filter(
    (row) => row.failure_reason === 'device_claim_failed'
  ).length;
  const hasCompleteExecutionSet = total > 0 && executions.length >= total;
  const allTerminal =
    hasCompleteExecutionSet && executions.every(isTerminalExecution);

  const allFailed = allTerminal && total > 0 && failed === total;

  return {
    total,
    failed,
    deviceClaimFailed,
    allTerminal,
    allFailed,
    allFailuresAreDeviceClaim: allFailed && deviceClaimFailed === failed
  };
}
