import type { FlowStep } from '../scenario-steps/types';
import type { BracketChildRef } from './step-tree-walk';

const generatedSessionKeys = new WeakMap<object, string>();
let nextSessionKey = 0;

export type PendingStepDetail = {
  sessionKey: string;
  step: FlowStep;
};

export function pendingStepForSession(
  pending: PendingStepDetail | null,
  sessionKey: string
): FlowStep | null {
  return pending?.sessionKey === sessionKey ? pending.step : null;
}

export function stepDetailSessionKey(step: FlowStep): string {
  const record = step as Record<string, unknown>;
  const persistedKey = record._fgId ?? record.id;
  if (typeof persistedKey === 'string' && persistedKey.length > 0) {
    return `step:${persistedKey}`;
  }

  let generatedKey = generatedSessionKeys.get(step);
  if (!generatedKey) {
    nextSessionKey += 1;
    generatedKey = `step:local-${nextSessionKey}`;
    generatedSessionKeys.set(step, generatedKey);
  }
  return generatedKey;
}

export function inheritStepDetailSession(
  previous: FlowStep,
  next: FlowStep
): FlowStep {
  generatedSessionKeys.set(next, stepDetailSessionKey(previous));
  return next;
}

function selectedSegmentForOperation(
  selectedPath: BracketChildRef[],
  operationPath: BracketChildRef[]
): {
  depth: number;
  selected: BracketChildRef;
  operation: BracketChildRef;
} | null {
  if (
    operationPath.length === 0 ||
    selectedPath.length < operationPath.length
  ) {
    return null;
  }
  const depth = operationPath.length - 1;
  for (let index = 0; index < depth; index += 1) {
    if (
      selectedPath[index]?.listKey !== operationPath[index]?.listKey ||
      selectedPath[index]?.ci !== operationPath[index]?.ci
    ) {
      return null;
    }
  }
  const selected = selectedPath[depth];
  const operation = operationPath[depth];
  if (!selected || !operation || selected.listKey !== operation.listKey) {
    return null;
  }
  return { depth, selected, operation };
}

function replacePathSegmentIndex(
  path: BracketChildRef[],
  depth: number,
  index: number
): BracketChildRef[] {
  const next = [...path];
  next[depth] = { ...next[depth]!, ci: index };
  return next;
}

export function shiftSelectedPathForInsert(
  selectedPath: BracketChildRef[] | null,
  insertPath: BracketChildRef[],
  count: number
): BracketChildRef[] | null {
  if (!selectedPath || count <= 0) {
    return selectedPath;
  }
  const segments = selectedSegmentForOperation(selectedPath, insertPath);
  if (!segments || segments.operation.ci > segments.selected.ci) {
    return selectedPath;
  }
  return replacePathSegmentIndex(
    selectedPath,
    segments.depth,
    segments.selected.ci + count
  );
}

export function shiftSelectedPathForRemove(
  selectedPath: BracketChildRef[] | null,
  removedPath: BracketChildRef[]
): BracketChildRef[] | null {
  if (!selectedPath) return selectedPath;
  const segments = selectedSegmentForOperation(selectedPath, removedPath);
  if (!segments) return selectedPath;
  if (segments.operation.ci === segments.selected.ci) return null;
  if (segments.operation.ci > segments.selected.ci) return selectedPath;
  return replacePathSegmentIndex(
    selectedPath,
    segments.depth,
    segments.selected.ci - 1
  );
}

export function shiftSelectedPathForMove(
  selectedPath: BracketChildRef[] | null,
  movedPath: BracketChildRef[],
  delta: -1 | 1
): BracketChildRef[] | null {
  if (!selectedPath) return selectedPath;
  const segments = selectedSegmentForOperation(selectedPath, movedPath);
  if (!segments) return selectedPath;

  let nextIndex = segments.selected.ci;
  if (segments.selected.ci === segments.operation.ci) {
    nextIndex = segments.operation.ci + delta;
  } else if (segments.selected.ci === segments.operation.ci + delta) {
    nextIndex = segments.operation.ci;
  }
  if (nextIndex === segments.selected.ci) return selectedPath;
  return replacePathSegmentIndex(selectedPath, segments.depth, nextIndex);
}
