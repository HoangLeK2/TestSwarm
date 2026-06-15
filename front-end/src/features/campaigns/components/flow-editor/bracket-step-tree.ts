import type { FlowStep } from '../scenario-steps/types';

export function getChildStep(
  step: FlowStep,
  listKey: string,
  ci: number
): FlowStep | null {
  if (listKey.startsWith('branches.')) {
    const bi = parseInt(listKey.split('.')[1] ?? '0', 10);
    return (step.branches as any[])?.[bi]?.steps?.[ci] ?? null;
  }
  return ((step as any)[listKey] as FlowStep[])?.[ci] ?? null;
}

export function removeFromStep(
  step: FlowStep,
  key: string,
  ci: number
): FlowStep {
  const next = { ...step } as any;
  if (key.startsWith('branches.')) {
    const bi = parseInt(key.split('.')[1] ?? '0');
    const branches = [...(next.branches ?? [])];
    branches[bi] = {
      ...branches[bi],
      steps: branches[bi].steps.filter((_: any, i: number) => i !== ci)
    };
    next.branches = branches;
  } else {
    next[key] = (next[key] ?? []).filter((_: any, i: number) => i !== ci);
  }
  return next as FlowStep;
}

export function insertIntoStep(
  step: FlowStep,
  key: string,
  at: number,
  newStep: FlowStep
): FlowStep {
  const next = { ...step } as any;
  if (key.startsWith('branches.')) {
    const bi = parseInt(key.split('.')[1] ?? '0');
    const branches = [...(next.branches ?? [])];
    const bSteps = [...(branches[bi].steps ?? [])];
    bSteps.splice(at, 0, newStep);
    branches[bi] = { ...branches[bi], steps: bSteps };
    next.branches = branches;
  } else {
    const arr = [...(next[key] ?? [])];
    arr.splice(at, 0, newStep);
    next[key] = arr;
  }
  return next as FlowStep;
}

export function updateChildInStep(
  step: FlowStep,
  key: string,
  ci: number,
  newChild: FlowStep
): FlowStep {
  const next = { ...step } as any;
  if (key.startsWith('branches.')) {
    const bi = parseInt(key.split('.')[1] ?? '0');
    const branches = [...(next.branches ?? [])];
    const bSteps = [...(branches[bi].steps ?? [])];
    bSteps[ci] = newChild;
    branches[bi] = { ...branches[bi], steps: bSteps };
    next.branches = branches;
  } else {
    const arr = [...(next[key] ?? [])];
    arr[ci] = newChild;
    next[key] = arr;
  }
  return next as FlowStep;
}

/** Apply a child edit using the latest parent snapshot (stable for debounced panel commits). */
export function applyChildStepEdit(
  parent: FlowStep,
  path: { listKey: string; ci: number } | null | undefined,
  child: FlowStep
): FlowStep | null {
  if (!path) return null;
  return updateChildInStep(parent, path.listKey, path.ci, child);
}
