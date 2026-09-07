import {
  isContainerType,
  type FlowStep
} from '../components/scenario-steps/types';

export type StepTreePathSegment = { listKey: string; ci: number };

export type StepTreeInsertLocationKind =
  | 'root'
  | 'then'
  | 'else'
  | 'loop'
  | 'random_branch'
  | 'nested_steps';

export type StepTreeInsertLocation = {
  path: StepTreePathSegment[];
  containerKey: string;
  insertIndex: number;
  depth: number;
  kind: StepTreeInsertLocationKind;
  labelKey:
    | 'rootSequence'
    | 'thenBranch'
    | 'elseBranch'
    | 'loopBody'
    | 'randomBranch'
    | 'nestedSteps';
  labelValues?: Record<string, number>;
};

export type StepTreeNodeKind = 'control' | 'runnable';

export type StepTreeNode = {
  step: FlowStep;
  path: StepTreePathSegment[];
  depth: number;
  parentType?: string;
  containerKey: string;
  nodeKind: StepTreeNodeKind;
  insertBefore: StepTreeInsertLocation;
  insertAfter: StepTreeInsertLocation;
  childInsertLocations: StepTreeInsertLocation[];
};

type ChildContainer = {
  listKey: string;
  steps: FlowStep[];
};

function childContainers(step: FlowStep): ChildContainer[] {
  if (!isContainerType(step.type)) return [];
  const record = step as FlowStep & {
    steps?: FlowStep[];
    then?: FlowStep[];
    else?: FlowStep[];
    branches?: Array<{ steps?: FlowStep[] }>;
  };

  if (
    step.type === 'loop' ||
    step.type === 'repeat' ||
    step.type === 'repeat_until'
  ) {
    return [{ listKey: 'steps', steps: record.steps ?? [] }];
  }

  if (
    step.type === 'if' ||
    step.type === 'if_element' ||
    step.type === 'if_variable' ||
    step.type === 'social_open_comments'
  ) {
    return [
      { listKey: 'then', steps: record.then ?? [] },
      { listKey: 'else', steps: record.else ?? [] }
    ];
  }

  if (step.type === 'random_pick') {
    return (record.branches ?? []).map((branch, index) => ({
      listKey: `branches.${index}`,
      steps: branch.steps ?? []
    }));
  }

  return [];
}

export function stepTreePathKey(path: StepTreePathSegment[]): string {
  return path.map(({ listKey, ci }) => `${listKey}:${ci}`).join('/');
}

export function insertLocationFromPath(
  path: StepTreePathSegment[]
): StepTreeInsertLocation {
  const last = path[path.length - 1] ?? { listKey: 'steps', ci: 0 };
  const depth = Math.max(0, path.length - 1);
  const base = {
    path,
    containerKey: last.listKey,
    insertIndex: last.ci,
    depth
  };

  if (last.listKey === 'then') {
    return { ...base, kind: 'then', labelKey: 'thenBranch' };
  }
  if (last.listKey === 'else') {
    return { ...base, kind: 'else', labelKey: 'elseBranch' };
  }
  if (last.listKey.startsWith('branches.')) {
    const branchIndex = Number.parseInt(last.listKey.split('.')[1] ?? '0', 10);
    return {
      ...base,
      kind: 'random_branch',
      labelKey: 'randomBranch',
      labelValues: {
        number: Number.isFinite(branchIndex) ? branchIndex + 1 : 1
      }
    };
  }
  if (last.listKey === 'steps' && path.length <= 1) {
    return { ...base, kind: 'root', labelKey: 'rootSequence' };
  }
  if (last.listKey === 'steps') {
    return { ...base, kind: 'loop', labelKey: 'loopBody' };
  }
  return { ...base, kind: 'nested_steps', labelKey: 'nestedSteps' };
}

export function insertLocationForChildList(
  pathFromRoot: Array<{ listKey: string; childIndex: number }> | undefined,
  listKey: string,
  insertIndex: number
): StepTreeInsertLocation {
  return insertLocationFromPath([
    ...(pathFromRoot ?? []).map((segment) => ({
      listKey: segment.listKey,
      ci: segment.childIndex
    })),
    { listKey, ci: insertIndex }
  ]);
}

function pushNodes(
  steps: FlowStep[],
  parentPath: StepTreePathSegment[],
  containerKey: string,
  depth: number,
  out: StepTreeNode[],
  parentType?: string
): void {
  steps.forEach((step, ci) => {
    if (!step.type) return;
    const path = [...parentPath, { listKey: containerKey, ci }];
    const children = childContainers(step);
    const isControlNode = isContainerType(step.type);
    out.push({
      step,
      path,
      depth,
      parentType,
      containerKey,
      nodeKind: isControlNode ? 'control' : 'runnable',
      insertBefore: insertLocationFromPath(path),
      insertAfter: insertLocationFromPath([
        ...parentPath,
        { listKey: containerKey, ci: ci + 1 }
      ]),
      childInsertLocations: children.map((child) =>
        insertLocationFromPath([
          ...path,
          { listKey: child.listKey, ci: child.steps.length }
        ])
      )
    });

    for (const child of children) {
      pushNodes(child.steps, path, child.listKey, depth + 1, out, step.type);
    }
  });
}

export function analyzeStepTree(steps: FlowStep[]): StepTreeNode[] {
  const out: StepTreeNode[] = [];
  pushNodes(steps, [], 'steps', 0, out);
  return out;
}
