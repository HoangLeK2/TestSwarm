import type { FlowStep } from '../components/scenario-steps/types';
import type { StepLogEntry, TemporalActivityEventSummary } from '../types';
import {
  executionTraceFromLog,
  executionTraceFromRecord,
  normalizeTracePathForMatch
} from './execution-trace';

export type WorkflowStepRowStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed';

export type FlatWorkflowStep = {
  step: FlowStep;
  flatIndex: number;
  depth: number;
  pathKey: string;
  tracePath: string;
  branchLabel?: string;
  rootIndex: number;
  localIndex: number;
};

export type WorkflowStepRow = FlatWorkflowStep & {
  logEntry?: StepLogEntry;
  status: WorkflowStepRowStatus;
};

export type WorkflowStepRows = WorkflowStepRow[] & {
  completedCount: number;
  failedCount: number;
  totalCount: number;
};

type ChildList = {
  listKey: string;
  branchLabel: string;
  traceBranch?: string;
  steps: FlowStep[];
};

function childLists(step: FlowStep): ChildList[] {
  const out: ChildList[] = [];
  const rec = step as FlowStep & {
    steps?: FlowStep[];
    then?: FlowStep[];
    else?: FlowStep[];
    branches?: Array<{ steps?: FlowStep[] }>;
  };

  if (rec.steps?.length) {
    out.push({
      listKey: 'steps',
      branchLabel:
        step.type === 'run_scenario'
          ? 'monitorStepBranchScenario'
          : 'monitorStepBranchLoop',
      steps: rec.steps
    });
  }
  if (rec.then?.length) {
    out.push({
      listKey: 'then',
      branchLabel: 'monitorStepBranchThen',
      traceBranch: 'then',
      steps: rec.then
    });
  }
  if (rec.else?.length) {
    out.push({
      listKey: 'else',
      branchLabel: 'monitorStepBranchElse',
      traceBranch: 'else',
      steps: rec.else
    });
  }
  rec.branches?.forEach((branch, branchIndex) => {
    if (!branch.steps?.length) return;
    out.push({
      listKey: `branches.${branchIndex}`,
      branchLabel: 'monitorStepBranchRandom',
      traceBranch: `branch${branchIndex}`,
      steps: branch.steps
    });
  });

  return out;
}

function stepTraceSegment(step: FlowStep, index: number): string {
  const raw = step as FlowStep & {
    id?: unknown;
    _id?: unknown;
    step_id?: unknown;
  };
  return String(raw.id ?? raw._id ?? raw.step_id ?? index).trim();
}

function pushSteps(
  steps: FlowStep[],
  out: FlatWorkflowStep[],
  depth: number,
  parentPath: string,
  parentTracePath: string,
  rootIndex: number,
  branchLabel?: string
): void {
  for (let index = 0; index < steps.length; index += 1) {
    const step = steps[index];
    if (!step?.type) continue;

    const ownRootIndex = depth === 0 ? index : rootIndex;
    const pathKey = `${parentPath}.${index}`;
    const segment = stepTraceSegment(step, index);
    const tracePath = parentTracePath
      ? `${parentTracePath}/${segment}`
      : segment;
    out.push({
      step,
      flatIndex: out.length,
      depth,
      pathKey,
      tracePath,
      branchLabel,
      rootIndex: ownRootIndex,
      localIndex: index
    });

    for (const childList of childLists(step)) {
      pushSteps(
        childList.steps,
        out,
        depth + 1,
        `${pathKey}.${childList.listKey}`,
        childList.traceBranch
          ? `${tracePath}.${childList.traceBranch}`
          : tracePath,
        ownRootIndex,
        childList.branchLabel
      );
    }
  }
}

export function flattenWorkflowSteps(steps: FlowStep[]): FlatWorkflowStep[] {
  const out: FlatWorkflowStep[] = [];
  pushSteps(steps, out, 0, 'steps', '', 0);
  return out;
}

function logStatus(log: StepLogEntry): WorkflowStepRowStatus {
  if (log.status === 'running') return 'running';
  return log.ok ? 'completed' : 'failed';
}

function reconcileRunningRows(
  rows: WorkflowStepRow[],
  isActive: boolean
): void {
  if (!isActive) return;

  const runningRows = rows.filter((row) => row.status === 'running');
  if (runningRows.length <= 1) {
    if (runningRows.length === 0) {
      const nextPending = rows.find((row) => row.status === 'pending');
      if (nextPending) nextPending.status = 'running';
    }
    return;
  }

  const keep = runningRows.reduce((best, row) =>
    row.flatIndex > best.flatIndex ? row : best
  );
  for (const row of rows) {
    if (row.status !== 'running' || row.pathKey === keep.pathKey) continue;
    const isAncestorOfKeep =
      row.flatIndex < keep.flatIndex &&
      row.rootIndex === keep.rootIndex &&
      row.depth < keep.depth;
    if (isAncestorOfKeep) continue;
    if (row.flatIndex < keep.flatIndex) {
      row.status =
        row.logEntry && row.logEntry.ok === false ? 'failed' : 'completed';
    }
  }
}

export type WorkflowCursor = {
  currentRootIndex: number;
  currentStepType: string;
  message: string;
};

export function deriveWorkflowCursor({
  executedSteps,
  isActive,
  fallbackCurrentStep = 0,
  fallbackStepType = '',
  fallbackMessage = ''
}: {
  executedSteps: StepLogEntry[];
  isActive: boolean;
  fallbackCurrentStep?: number;
  fallbackStepType?: string;
  fallbackMessage?: string;
}): WorkflowCursor {
  if (!isActive || executedSteps.length === 0) {
    return {
      currentRootIndex: fallbackCurrentStep,
      currentStepType: fallbackStepType,
      message: fallbackMessage
    };
  }

  const running = [...executedSteps]
    .reverse()
    .find((step) => step.status === 'running');
  if (running) {
    return {
      currentRootIndex: running.index,
      currentStepType: running.step_type || running.type || fallbackStepType,
      message: running.message ?? fallbackMessage
    };
  }

  const depthZero = executedSteps.filter((step) => (step.depth ?? 0) === 0);
  if (depthZero.length > 0) {
    const maxIndex = Math.max(...depthZero.map((step) => step.index));
    const last = depthZero.find((step) => step.index === maxIndex);
    if (last && last.ok !== false) {
      return {
        currentRootIndex: maxIndex + 1,
        currentStepType: fallbackStepType,
        message: fallbackMessage
      };
    }
    if (last) {
      return {
        currentRootIndex: maxIndex,
        currentStepType: last.step_type || last.type || fallbackStepType,
        message: last.message ?? fallbackMessage
      };
    }
  }

  return {
    currentRootIndex: fallbackCurrentStep,
    currentStepType: fallbackStepType,
    message: fallbackMessage
  };
}

export function resolveCurrentRootIndex({
  executedSteps,
  isActive,
  progressCurrentStep
}: {
  executedSteps: StepLogEntry[];
  isActive: boolean;
  progressCurrentStep?: number | null;
}): number {
  const derived = deriveWorkflowCursor({
    executedSteps,
    isActive,
    fallbackCurrentStep: progressCurrentStep ?? 0
  }).currentRootIndex;

  if (
    progressCurrentStep != null &&
    progressCurrentStep > 0 &&
    progressCurrentStep > derived
  ) {
    return progressCurrentStep;
  }

  return derived;
}

export function normalizeTemporalStepLogEntry(
  raw: Record<string, unknown>
): StepLogEntry {
  const type = String(raw.step_type ?? raw.type ?? '');
  const status = typeof raw.status === 'string' ? raw.status.toLowerCase() : '';
  const ok =
    raw.ok !== false &&
    !['failed', 'error', 'cancelled', 'canceled'].includes(status);
  const trace =
    raw.trace && typeof raw.trace === 'object'
      ? (raw.trace as Record<string, unknown>)
      : undefined;
  const details =
    raw.details && typeof raw.details === 'object'
      ? (raw.details as Record<string, unknown>)
      : undefined;
  const evidence =
    raw.evidence && typeof raw.evidence === 'object'
      ? (raw.evidence as Record<string, unknown>)
      : details?.evidence && typeof details.evidence === 'object'
        ? (details.evidence as Record<string, unknown>)
        : undefined;
  const temporalActivityEvents = Array.isArray(raw.temporal_activity_events)
    ? (raw.temporal_activity_events.filter(
        (item): item is TemporalActivityEventSummary =>
          Boolean(item) && typeof item === 'object'
      ) as TemporalActivityEventSummary[])
    : undefined;
  const traceSummary = executionTraceFromRecord(raw);
  return {
    index: Number(raw.index ?? raw.step_index ?? 0),
    occurrence_key:
      typeof raw.occurrence_key === 'string' ? raw.occurrence_key : undefined,
    step_id: typeof raw.step_id === 'string' ? raw.step_id : null,
    type,
    step_type: type,
    ok,
    message: typeof raw.message === 'string' ? raw.message : null,
    depth: Number(raw.depth ?? 0),
    status:
      status === 'running' || status === 'in_progress'
        ? 'running'
        : ok
          ? 'completed'
          : 'failed',
    output: typeof raw.output === 'string' ? raw.output : null,
    exit_code: typeof raw.exit_code === 'number' ? raw.exit_code : null,
    save_as: typeof raw.save_as === 'string' ? raw.save_as : null,
    output_truncated: Boolean(raw.output_truncated),
    step_path: traceSummary.stepPath,
    loop_id: traceSummary.loopId,
    loop_iter: traceSummary.loopIter,
    branch: traceSummary.branch,
    reason_code: traceSummary.reasonCode,
    evidence,
    details: trace ? { ...(details ?? {}), trace } : details,
    trace,
    temporal_activity_events: temporalActivityEvents
  };
}

function stepLogMergeKey(entry: StepLogEntry): string {
  if (entry.occurrence_key) return entry.occurrence_key;
  return `${entry.depth ?? 0}:${entry.index}:${entry.step_id ?? entry.step_type ?? ''}`;
}

export function mergeStepLogEntries(
  ...sources: StepLogEntry[][]
): StepLogEntry[] {
  const map = new Map<string, StepLogEntry>();
  for (const source of sources) {
    for (const entry of source) {
      const key = stepLogMergeKey(entry);
      const existing = map.get(key);
      if (!existing) {
        map.set(key, entry);
        continue;
      }
      const mergedTemporalActivityEvents = mergeTemporalActivityEvents(
        existing.temporal_activity_events,
        entry.temporal_activity_events
      );
      if (entry.status === 'running') {
        map.set(key, {
          ...entry,
          temporal_activity_events: mergedTemporalActivityEvents
        });
        continue;
      }
      if (existing.status === 'running') {
        map.set(key, {
          ...entry,
          temporal_activity_events: mergedTemporalActivityEvents
        });
        continue;
      }
      if (mergedTemporalActivityEvents) {
        map.set(key, {
          ...existing,
          temporal_activity_events: mergedTemporalActivityEvents
        });
      }
    }
  }
  return Array.from(map.values()).sort(
    (a, b) =>
      (a.depth ?? 0) - (b.depth ?? 0) ||
      a.index - b.index ||
      stepLogMergeKey(a).localeCompare(stepLogMergeKey(b))
  );
}

function mergeTemporalActivityEvents(
  first?: TemporalActivityEventSummary[],
  second?: TemporalActivityEventSummary[]
): TemporalActivityEventSummary[] | undefined {
  const merged = [...(first ?? []), ...(second ?? [])];
  if (merged.length === 0) return undefined;

  const bySignature = new Map<string, TemporalActivityEventSummary>();
  for (const event of merged) {
    const signature = `${event.event_type}:${event.activity_id ?? ''}:${
      event.step_activity_id ?? ''
    }:${event.activity_attempt ?? ''}:${event.occurred_at ?? ''}`;
    bySignature.set(signature, event);
  }
  return Array.from(bySignature.values()).slice(-8);
}

function logType(log: StepLogEntry): string {
  return log.step_type || log.type || '';
}

function logPath(log: StepLogEntry): string | null {
  const traceSummary = executionTraceFromLog(log);
  const details = log.details ?? {};
  const raw =
    (log as StepLogEntry & { path_key?: unknown; step_path?: unknown })
      .path_key ??
    (log as StepLogEntry & { path?: unknown }).path ??
    details.path_key ??
    details.step_path ??
    details.path;
  if (typeof raw === 'string' && raw.trim()) return raw;
  if (Array.isArray(raw)) return raw.join('.');
  return traceSummary.stepPath;
}

function logStepId(log: StepLogEntry): string | null {
  const details = log.details ?? {};
  const raw =
    (log as StepLogEntry & { step_id?: unknown }).step_id ?? details.step_id;
  return typeof raw === 'string' && raw.trim() ? raw : null;
}

function matchesType(flat: FlatWorkflowStep, log: StepLogEntry): boolean {
  const type = logType(log);
  return !type || flat.step.type === type;
}

function addIndex(
  index: Map<string, FlatWorkflowStep[]>,
  key: string | null | undefined,
  flat: FlatWorkflowStep
): void {
  if (!key) return;
  const rows = index.get(key);
  if (rows) {
    rows.push(flat);
    return;
  }
  index.set(key, [flat]);
}

function flatStepId(flat: FlatWorkflowStep): string | null {
  const step = flat.step as FlowStep & {
    id?: unknown;
    _id?: unknown;
    step_id?: unknown;
  };
  const raw = step.id ?? step._id ?? step.step_id;
  return typeof raw === 'string' && raw.trim() ? raw : null;
}

function depthLocalKey(
  depth: number,
  localIndex: number,
  type: string
): string {
  return `${depth}:${localIndex}:${type}`;
}

function rootKey(rootIndex: number, type: string): string {
  return `${rootIndex}:${type}`;
}

function indexedLookup(
  index: Map<string, FlatWorkflowStep[]>,
  keys: Array<string | null | undefined>
): FlatWorkflowStep[] {
  const out: FlatWorkflowStep[] = [];
  const seen = new Set<string>();
  for (const key of keys) {
    if (!key) continue;
    for (const row of index.get(key) ?? []) {
      if (seen.has(row.pathKey)) continue;
      seen.add(row.pathKey);
      out.push(row);
    }
  }
  return out;
}

function assignLogs(
  flatSteps: FlatWorkflowStep[],
  logs: StepLogEntry[]
): Map<string, StepLogEntry> {
  const assigned = new Map<string, StepLogEntry>();
  const used = new Set<string>();
  const byPath = new Map<string, FlatWorkflowStep[]>();
  const byTracePath = new Map<string, FlatWorkflowStep[]>();
  const byStepId = new Map<string, FlatWorkflowStep[]>();
  const byDepthLocal = new Map<string, FlatWorkflowStep[]>();
  const byRoot = new Map<string, FlatWorkflowStep[]>();

  for (const flat of flatSteps) {
    const normalizedTracePath = normalizeTracePathForMatch(flat.tracePath);
    addIndex(byPath, flat.pathKey, flat);
    addIndex(byTracePath, flat.tracePath, flat);
    addIndex(byTracePath, normalizedTracePath, flat);
    addIndex(byStepId, flatStepId(flat), flat);
    addIndex(
      byDepthLocal,
      depthLocalKey(flat.depth, flat.localIndex, ''),
      flat
    );
    addIndex(
      byDepthLocal,
      depthLocalKey(flat.depth, flat.localIndex, flat.step.type),
      flat
    );
    if (flat.depth === 0) {
      addIndex(byRoot, rootKey(flat.rootIndex, ''), flat);
      addIndex(byRoot, rootKey(flat.rootIndex, flat.step.type), flat);
    }
  }

  for (const log of logs) {
    const explicitPath = logPath(log);
    const normalizedExplicitPath = normalizeTracePathForMatch(explicitPath);
    let candidates = explicitPath ? indexedLookup(byPath, [explicitPath]) : [];
    if (candidates.length === 0 && explicitPath) {
      candidates = indexedLookup(byTracePath, [
        explicitPath,
        normalizedExplicitPath
      ]);
    }

    const stepId = candidates.length === 0 ? logStepId(log) : null;
    if (stepId) {
      candidates = byStepId.get(stepId) ?? [];
    }

    if (candidates.length === 0) {
      const type = logType(log);
      candidates = indexedLookup(byDepthLocal, [
        depthLocalKey(log.depth ?? 0, log.index, type),
        type ? null : depthLocalKey(log.depth ?? 0, log.index, '')
      ]).filter((flat) => matchesType(flat, log));
    }

    if (candidates.length === 0 && (log.depth ?? 0) === 0) {
      const type = logType(log);
      candidates = indexedLookup(byRoot, [
        rootKey(log.index, type),
        type ? null : rootKey(log.index, '')
      ]).filter((flat) => matchesType(flat, log));
    }

    if (candidates.length === 0) continue;
    const target =
      candidates.find((flat) => !used.has(flat.pathKey)) ?? candidates[0];
    assigned.set(target.pathKey, log);
    used.add(target.pathKey);
  }

  return assigned;
}

function placeholderRows(logs: StepLogEntry[]): WorkflowStepRows {
  const rows = logs.map((log, index) => ({
    step: { type: logType(log) || 'unknown' },
    flatIndex: index,
    depth: log.depth ?? 0,
    pathKey: `log.${index}`,
    tracePath: log.step_path ?? `log.${index}`,
    rootIndex: log.index,
    localIndex: log.index,
    logEntry: log,
    status: logStatus(log)
  })) as WorkflowStepRows;
  rows.completedCount = rows.filter((row) => row.status === 'completed').length;
  rows.failedCount = rows.filter((row) => row.status === 'failed').length;
  rows.totalCount = rows.length;
  return rows;
}

export function buildWorkflowStepRows({
  scenarioSteps,
  executedSteps,
  currentRootIndex,
  isActive,
  isCompleted = false
}: {
  scenarioSteps: FlowStep[];
  executedSteps: StepLogEntry[];
  currentRootIndex: number;
  isActive: boolean;
  isCompleted?: boolean;
}): WorkflowStepRows {
  const flatSteps = flattenWorkflowSteps(scenarioSteps);
  if (flatSteps.length === 0) return placeholderRows(executedSteps);

  const logByPath = assignLogs(flatSteps, executedSteps);
  const rows = flatSteps.map((flat) => {
    const logEntry = logByPath.get(flat.pathKey);
    let status: WorkflowStepRowStatus = 'pending';
    if (logEntry) {
      status = logStatus(logEntry);
      if (
        status === 'running' &&
        isActive &&
        flat.rootIndex < currentRootIndex
      ) {
        status = logEntry.ok === false ? 'failed' : 'completed';
      }
    } else if (isCompleted) {
      status = 'completed';
    } else if (
      isActive &&
      flat.depth === 0 &&
      flat.rootIndex === currentRootIndex
    ) {
      status = 'running';
    } else if (flat.rootIndex < currentRootIndex) {
      status = 'completed';
    }
    return { ...flat, logEntry, status };
  }) as WorkflowStepRows;

  reconcileRunningRows(rows, isActive);

  rows.completedCount = rows.filter((row) => row.status === 'completed').length;
  rows.failedCount = rows.filter((row) => row.status === 'failed').length;
  rows.totalCount = rows.length;
  return rows;
}
