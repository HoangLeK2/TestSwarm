import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';

export type StepTreePath = Array<string | number>;

export function stepPathKey(path: StepTreePath | null): string {
  return path ? JSON.stringify(path) : '';
}

export function findStepAtPath(
  steps: FlowStep[],
  path: StepTreePath | null
): FlowStep | null {
  if (!path || path.length === 0) return null;
  let arr: FlowStep[] = steps;
  let step: FlowStep | undefined;
  for (let i = 0; i < path.length; ) {
    const index = path[i];
    if (typeof index !== 'number') return null;
    step = arr[index];
    if (!step) return null;
    i += 1;
    if (i >= path.length) return step;
    const field = path[i];
    if (field === 'then' || field === 'else' || field === 'steps') {
      arr = Array.isArray(step[field]) ? step[field] : [];
      i += 1;
      continue;
    }
    if (field === 'branches') {
      const branchIndex = path[i + 1];
      const stepsField = path[i + 2];
      if (typeof branchIndex !== 'number' || stepsField !== 'steps') {
        return null;
      }
      const branch = Array.isArray(step.branches)
        ? step.branches[branchIndex]
        : null;
      arr = Array.isArray(branch?.steps) ? branch.steps : [];
      i += 3;
      continue;
    }
    return null;
  }
  return step ?? null;
}

export function replaceStepAtPath(
  steps: FlowStep[],
  path: StepTreePath,
  replacement: FlowStep
): FlowStep[] {
  return updateArrayAtPath(steps, path, (arr, index) => {
    const next = [...arr];
    next[index] = replacement;
    return next;
  });
}

export function insertStepAtContainerPath(
  steps: FlowStep[],
  containerPath: StepTreePath,
  index: number,
  step: FlowStep
): FlowStep[] {
  return updateContainerAtPath(steps, containerPath, (arr) => {
    const next = [...arr];
    next.splice(Math.max(0, Math.min(index, next.length)), 0, step);
    return next;
  });
}

export function moveStepInContainerPath(
  steps: FlowStep[],
  containerPath: StepTreePath,
  fromIndex: number,
  toIndex: number
): FlowStep[] {
  if (fromIndex === toIndex) return steps;
  return updateContainerAtPath(steps, containerPath, (arr) => {
    if (
      fromIndex < 0 ||
      fromIndex >= arr.length ||
      toIndex < 0 ||
      toIndex > arr.length
    ) {
      return arr;
    }
    const next = [...arr];
    const [item] = next.splice(fromIndex, 1);
    if (!item) return arr;
    const adjusted = fromIndex < toIndex ? toIndex - 1 : toIndex;
    next.splice(adjusted, 0, item);
    return next;
  });
}

export type MoveStepResult = {
  steps: FlowStep[];
  path: StepTreePath;
};

export function moveStepBetweenContainerPaths(
  steps: FlowStep[],
  fromContainerPath: StepTreePath,
  fromIndex: number,
  toContainerPath: StepTreePath,
  toIndex: number
): MoveStepResult | null {
  const source = findContainerAtPath(steps, fromContainerPath);
  const target = findContainerAtPath(steps, toContainerPath);
  if (
    !source ||
    !target ||
    fromIndex < 0 ||
    fromIndex >= source.length ||
    toIndex < 0 ||
    toIndex > target.length
  ) {
    return null;
  }

  if (pathsEqual(fromContainerPath, toContainerPath)) {
    const next = moveStepInContainerPath(
      steps,
      fromContainerPath,
      fromIndex,
      toIndex
    );
    const finalIndex = fromIndex < toIndex ? toIndex - 1 : toIndex;
    return {
      steps: next,
      path: [...fromContainerPath, finalIndex]
    };
  }

  const sourceStepPath = [...fromContainerPath, fromIndex];
  if (pathStartsWith(toContainerPath, sourceStepPath)) return null;

  const movedStep = source[fromIndex];
  const adjustedTargetPath = adjustPathAfterRemoval(
    toContainerPath,
    fromContainerPath,
    fromIndex
  );
  const withoutSource = updateContainerAtPath(steps, fromContainerPath, (arr) =>
    arr.filter((_, index) => index !== fromIndex)
  );
  const adjustedTarget = findContainerAtPath(withoutSource, adjustedTargetPath);
  if (!adjustedTarget) return null;
  const finalIndex = Math.min(toIndex, adjustedTarget.length);
  const next = updateContainerAtPath(
    withoutSource,
    adjustedTargetPath,
    (arr) => {
      const copy = [...arr];
      copy.splice(finalIndex, 0, movedStep);
      return copy;
    }
  );

  return {
    steps: next,
    path: [...adjustedTargetPath, finalIndex]
  };
}

function findContainerAtPath(
  steps: FlowStep[],
  path: StepTreePath
): FlowStep[] | null {
  if (path.length === 0) return steps;
  const index = path[0];
  if (typeof index !== 'number') return null;
  const step = steps[index];
  if (!step) return null;
  const field = path[1];
  if (field === 'then' || field === 'else' || field === 'steps') {
    const child = step[field];
    if (!Array.isArray(child)) return null;
    return findContainerAtPath(child, path.slice(2));
  }
  if (field === 'branches') {
    const branchIndex = path[2];
    if (typeof branchIndex !== 'number' || path[3] !== 'steps') return null;
    const branch = Array.isArray(step.branches)
      ? step.branches[branchIndex]
      : null;
    if (!Array.isArray(branch?.steps)) return null;
    return findContainerAtPath(branch.steps, path.slice(4));
  }
  return null;
}

function pathsEqual(a: StepTreePath, b: StepTreePath): boolean {
  return a.length === b.length && a.every((part, index) => part === b[index]);
}

function pathStartsWith(path: StepTreePath, prefix: StepTreePath): boolean {
  return (
    path.length >= prefix.length &&
    prefix.every((part, index) => part === path[index])
  );
}

function adjustPathAfterRemoval(
  path: StepTreePath,
  sourceContainerPath: StepTreePath,
  sourceIndex: number
): StepTreePath {
  if (!pathStartsWith(path, sourceContainerPath)) return path;
  const indexPosition = sourceContainerPath.length;
  const siblingIndex = path[indexPosition];
  if (typeof siblingIndex !== 'number' || siblingIndex <= sourceIndex) {
    return path;
  }
  const adjusted = [...path];
  adjusted[indexPosition] = siblingIndex - 1;
  return adjusted;
}

function updateArrayAtPath(
  arr: FlowStep[],
  path: StepTreePath,
  updater: (arr: FlowStep[], index: number) => FlowStep[]
): FlowStep[] {
  const index = path[0];
  if (typeof index !== 'number') return arr;
  if (path.length === 1) return updater(arr, index);
  const step = arr[index];
  if (!step) return arr;
  const next = [...arr];
  next[index] = updateNestedStep(step, path.slice(1), (childArr, childPath) =>
    updateArrayAtPath(childArr, childPath, updater)
  );
  return next;
}

function updateContainerAtPath(
  arr: FlowStep[],
  path: StepTreePath,
  updater: (arr: FlowStep[]) => FlowStep[]
): FlowStep[] {
  if (path.length === 0) return updater(arr);
  const index = path[0];
  if (typeof index !== 'number') return arr;
  const step = arr[index];
  if (!step) return arr;
  const next = [...arr];
  next[index] = updateNestedStep(step, path.slice(1), (childArr, childPath) =>
    updateContainerAtPath(childArr, childPath, updater)
  );
  return next;
}

function updateNestedStep(
  step: FlowStep,
  path: StepTreePath,
  updater: (arr: FlowStep[], path: StepTreePath) => FlowStep[]
): FlowStep {
  const field = path[0];
  if (field === 'then' || field === 'else' || field === 'steps') {
    return {
      ...step,
      [field]: updater(
        Array.isArray(step[field]) ? step[field] : [],
        path.slice(1)
      )
    } as FlowStep;
  }
  if (field === 'branches') {
    const branchIndex = path[1];
    const stepsField = path[2];
    if (typeof branchIndex !== 'number' || stepsField !== 'steps') return step;
    const branches = Array.isArray(step.branches) ? [...step.branches] : [];
    const branch = branches[branchIndex] ?? { weight: 1, steps: [] };
    branches[branchIndex] = {
      ...branch,
      steps: updater(
        Array.isArray(branch.steps) ? branch.steps : [],
        path.slice(3)
      )
    };
    return { ...step, branches } as FlowStep;
  }
  return step;
}
