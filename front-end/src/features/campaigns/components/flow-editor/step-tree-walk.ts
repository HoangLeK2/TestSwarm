import type { FlowStep } from '../scenario-steps/types.ts';
import { isContainerType } from '../scenario-steps/types.ts';

export type BracketChildRef = { listKey: string; ci: number };

export type StepTreeVisit = {
  step: FlowStep;
  /** Bracket path from root steps[] to this node. */
  path: BracketChildRef[];
  depth: number;
};

function childLists(
  step: FlowStep
): Array<{ listKey: string; steps: FlowStep[] }> {
  const out: Array<{ listKey: string; steps: FlowStep[] }> = [];
  if (step.type === 'random_pick') {
    const branches = (
      step as FlowStep & { branches?: Array<{ steps?: FlowStep[] }> }
    ).branches;
    branches?.forEach((br, bi) => {
      out.push({ listKey: `branches.${bi}`, steps: br.steps ?? [] });
    });
    return out;
  }
  if (!isContainerType(step.type)) return out;
  if (
    step.type === 'loop' ||
    step.type === 'repeat' ||
    step.type === 'repeat_until'
  ) {
    out.push({
      listKey: 'steps',
      steps: (step as FlowStep & { steps?: FlowStep[] }).steps ?? []
    });
  }
  const thenElse = step as FlowStep & { then?: FlowStep[]; else?: FlowStep[] };
  if (thenElse.then?.length)
    out.push({ listKey: 'then', steps: thenElse.then });
  if (thenElse.else?.length)
    out.push({ listKey: 'else', steps: thenElse.else });
  return out;
}

function walkChildren(
  steps: FlowStep[],
  listKey: string,
  parentPath: BracketChildRef[],
  depth: number,
  out: StepTreeVisit[]
): void {
  for (let ci = 0; ci < steps.length; ci++) {
    const step = steps[ci]!;
    if (!step.type) continue;
    const path = [...parentPath, { listKey, ci }];
    out.push({ step, path, depth });
    for (const childList of childLists(step)) {
      walkChildren(childList.steps, childList.listKey, path, depth + 1, out);
    }
  }
}

/** Depth-first walk of all executable steps with bracket edit paths. */
export function walkFlowStepsWithPaths(steps: FlowStep[]): StepTreeVisit[] {
  const out: StepTreeVisit[] = [];
  for (let ci = 0; ci < steps.length; ci++) {
    const step = steps[ci]!;
    if (!step.type) continue;
    out.push({ step, path: [{ listKey: 'steps', ci }], depth: 0 });
    for (const childList of childLists(step)) {
      walkChildren(
        childList.steps,
        childList.listKey,
        [{ listKey: 'steps', ci }],
        1,
        out
      );
    }
  }
  return out;
}

export function countStepTypes(steps: FlowStep[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const { step } of walkFlowStepsWithPaths(steps)) {
    counts.set(step.type, (counts.get(step.type) ?? 0) + 1);
  }
  return counts;
}

/** Resolve a step at bracket path by drilling from root steps. */
export function resolveStepAtPath(
  rootSteps: FlowStep[],
  path: BracketChildRef[]
): FlowStep | null {
  if (path.length === 0) return null;
  const first = path[0]!;
  if (first.listKey !== 'steps') return null;
  let current: FlowStep | null = rootSteps[first.ci] ?? null;
  for (let i = 1; i < path.length; i++) {
    if (!current) return null;
    const { listKey, ci } = path[i]!;
    if (listKey.startsWith('branches.')) {
      const bi = parseInt(listKey.split('.')[1] ?? '0', 10);
      current =
        (current as FlowStep & { branches?: Array<{ steps?: FlowStep[] }> })
          .branches?.[bi]?.steps?.[ci] ?? null;
    } else {
      current =
        ((current as Record<string, unknown>)[listKey] as FlowStep[])?.[ci] ??
        null;
    }
  }
  return current;
}

/** Apply nested child edit from root using full bracket path. */
export function updateStepAtPath(
  rootSteps: FlowStep[],
  path: BracketChildRef[],
  replacement: FlowStep
): FlowStep[] {
  if (path.length === 0) return rootSteps;

  function patchAt(
    siblings: FlowStep[],
    idx: number,
    rest: BracketChildRef[],
    value: FlowStep
  ): FlowStep[] {
    const next = [...siblings];
    if (rest.length === 0) {
      next[idx] = value;
      return next;
    }
    const parent = siblings[idx];
    if (!parent) return siblings;
    next[idx] = patchInParent(parent, rest, value);
    return next;
  }

  function patchInParent(
    parent: FlowStep,
    rest: BracketChildRef[],
    value: FlowStep
  ): FlowStep {
    const { listKey, ci } = rest[0]!;
    const tail = rest.slice(1);
    const next = { ...parent } as Record<string, unknown>;
    if (listKey.startsWith('branches.')) {
      const bi = parseInt(listKey.split('.')[1] ?? '0', 10);
      const branches = [
        ...((next.branches as Array<{ steps: FlowStep[]; weight?: number }>) ??
          [])
      ];
      const bSteps = [...(branches[bi]?.steps ?? [])];
      bSteps[ci] =
        tail.length === 0 ? value : patchInParent(bSteps[ci]!, tail, value);
      branches[bi] = { ...branches[bi], steps: bSteps };
      next.branches = branches;
    } else {
      const arr = [...((next[listKey] as FlowStep[]) ?? [])];
      arr[ci] =
        tail.length === 0 ? value : patchInParent(arr[ci]!, tail, value);
      next[listKey] = arr;
    }
    return next as FlowStep;
  }

  const { listKey, ci } = path[0]!;
  if (listKey !== 'steps') return rootSteps;
  return patchAt(rootSteps, ci, path.slice(1), replacement);
}

/** Scale loop body for perf stress tests. */
export function amplifyLoopSteps(
  steps: FlowStep[],
  factor: number
): FlowStep[] {
  return steps.map((step) => {
    if (step.type !== 'loop') return step;
    const loop = step as FlowStep & { steps?: FlowStep[] };
    const body = loop.steps ?? [];
    const amplified: FlowStep[] = [];
    for (let i = 0; i < factor; i++) {
      amplified.push(
        ...body.map((s, j) => ({
          ...s,
          id: `${(s as { id?: string }).id ?? s.type}-${i}-${j}`
        }))
      );
    }
    return { ...loop, steps: amplified };
  });
}
