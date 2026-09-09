import type { FlowStep } from '../scenario-steps/types';
import {
  resolveStepAtPath,
  updateStepAtPath,
  type BracketChildRef
} from './step-tree-walk';

export function insertStepAtPath(
  rootSteps: FlowStep[],
  path: BracketChildRef[],
  step: FlowStep
): FlowStep[] {
  return insertStepsAtPath(rootSteps, path, [step]);
}

export function insertStepsAtPath(
  rootSteps: FlowStep[],
  path: BracketChildRef[],
  steps: FlowStep[]
): FlowStep[] {
  if (steps.length === 0) return rootSteps;
  const last = path[path.length - 1];
  if (!last) return [...rootSteps, ...steps];

  if (path.length === 1) {
    const next = [...rootSteps];
    next.splice(last.ci, 0, ...steps);
    return next;
  }

  const parentPath = path.slice(0, -1);
  const parent = resolveStepAtPath(rootSteps, parentPath);
  if (!parent) return rootSteps;
  const nextParent = { ...parent } as Record<string, unknown>;

  if (last.listKey.startsWith('branches.')) {
    const bi = Number.parseInt(last.listKey.split('.')[1] ?? '0', 10);
    const branches = [
      ...((nextParent.branches as Array<{ steps?: FlowStep[] }>) ?? [])
    ];
    const branch = branches[bi];
    if (!branch) return rootSteps;
    const branchSteps = [...(branch.steps ?? [])];
    branchSteps.splice(last.ci, 0, ...steps);
    branches[bi] = { ...branch, steps: branchSteps };
    nextParent.branches = branches;
  } else {
    const siblings = [
      ...((nextParent[last.listKey] as FlowStep[] | undefined) ?? [])
    ];
    siblings.splice(last.ci, 0, ...steps);
    nextParent[last.listKey] = siblings;
  }

  return updateStepAtPath(rootSteps, parentPath, nextParent as FlowStep);
}
