import { isContainerType, type FlowStep } from '../scenario-steps/types';
import type { BracketChildRef, StepTreeVisit } from './step-tree-walk';

export type VirtualFlowScope = {
  id: string;
  type: FlowStep['type'];
  depth: number;
};

export type VirtualFlowRow =
  | (StepTreeVisit & {
      kind: 'step';
      key: string;
      scopes: VirtualFlowScope[];
    })
  | {
      kind: 'branch';
      key: string;
      /** Key in `campaignsFeature.stepEditor.stepFields` — the row renders it. */
      labelKey: string;
      labelValues?: Record<string, number>;
      /**
       * What the branch means, independent of its wording. The marker used to
       * be picked by substring-matching the Vietnamese label, which silently
       * mislabels every branch as soon as the label is translated.
       */
      branch: 'then' | 'else' | 'loop' | 'pick';
      count: number;
      depth: number;
      insertPath: BracketChildRef[];
      scopes: VirtualFlowScope[];
    }
  | {
      kind: 'end';
      key: string;
      labelKey: string;
      labelValues?: Record<string, number>;
      depth: number;
      scopes: VirtualFlowScope[];
    };

function pathKey(path: BracketChildRef[]): string {
  return path.map(({ listKey, ci }) => `${listKey}:${ci}`).join('/');
}

function isConditional(step: FlowStep): boolean {
  return (
    step.type === 'if' ||
    step.type === 'if_element' ||
    step.type === 'if_variable' ||
    step.type === 'social_open_comments' ||
    step.type === 'social_open_comments'
  );
}

function projectList(
  steps: FlowStep[],
  listKey: string,
  parentPath: BracketChildRef[],
  depth: number,
  scopes: VirtualFlowScope[],
  rows: VirtualFlowRow[]
): void {
  steps.forEach((step, ci) => {
    if (!step.type) return;
    const path = [...parentPath, { listKey, ci }];
    const ownerKey = pathKey(path);
    rows.push({
      kind: 'step',
      key: `step:${ownerKey}`,
      step,
      path,
      depth,
      scopes
    });

    if (!isContainerType(step.type)) return;
    const scope: VirtualFlowScope = {
      id: ownerKey,
      type: step.type,
      depth
    };
    const nestedScopes = [...scopes, scope];

    if (
      step.type === 'loop' ||
      step.type === 'repeat' ||
      step.type === 'repeat_until'
    ) {
      const body = step.steps ?? [];
      rows.push({
        kind: 'branch',
        key: `branch:${ownerKey}:steps`,
        labelKey: 'branchLoopBody',
        branch: 'loop',
        count: body.length,
        depth: depth + 1,
        insertPath: [...path, { listKey: 'steps', ci: body.length }],
        scopes: nestedScopes
      });
      projectList(body, 'steps', path, depth + 1, nestedScopes, rows);
      rows.push({
        kind: 'end',
        key: `end:${ownerKey}`,
        labelKey: 'branchLoopEnd',
        depth,
        scopes: nestedScopes
      });
      return;
    }

    if (isConditional(step)) {
      const isFbTap =
        step.type === 'social_open_comments' ||
        step.type === 'social_open_comments';
      const thenSteps = step.then ?? [];
      const elseSteps = step.else ?? [];
      rows.push({
        kind: 'branch',
        key: `branch:${ownerKey}:then`,
        labelKey: isFbTap ? 'branchWhenFound' : 'branchIfTrue',
        branch: 'then',
        count: thenSteps.length,
        depth: depth + 1,
        insertPath: [...path, { listKey: 'then', ci: thenSteps.length }],
        scopes: nestedScopes
      });
      projectList(thenSteps, 'then', path, depth + 1, nestedScopes, rows);
      rows.push({
        kind: 'branch',
        key: `branch:${ownerKey}:else`,
        labelKey: isFbTap ? 'branchWhenNotFound' : 'branchIfFalse',
        branch: 'else',
        count: elseSteps.length,
        depth: depth + 1,
        insertPath: [...path, { listKey: 'else', ci: elseSteps.length }],
        scopes: nestedScopes
      });
      projectList(elseSteps, 'else', path, depth + 1, nestedScopes, rows);
      rows.push({
        kind: 'end',
        key: `end:${ownerKey}`,
        labelKey: 'branchIfEnd',
        depth,
        scopes: nestedScopes
      });
      return;
    }

    if (step.type === 'random_pick') {
      const branches = (
        step as FlowStep & { branches?: Array<{ steps?: FlowStep[] }> }
      ).branches;
      (branches ?? []).forEach((branch, branchIndex) => {
        const branchSteps = branch.steps ?? [];
        const branchKey = `branches.${branchIndex}`;
        rows.push({
          kind: 'branch',
          key: `branch:${ownerKey}:${branchKey}`,
          labelKey: 'branchNumbered',
          labelValues: { number: branchIndex + 1 },
          branch: 'pick',
          count: branchSteps.length,
          depth: depth + 1,
          insertPath: [...path, { listKey: branchKey, ci: branchSteps.length }],
          scopes: nestedScopes
        });
        projectList(
          branchSteps,
          branchKey,
          path,
          depth + 1,
          nestedScopes,
          rows
        );
      });
      rows.push({
        kind: 'end',
        key: `end:${ownerKey}`,
        labelKey: 'branchPickEnd',
        depth,
        scopes: nestedScopes
      });
    }
  });
}

export function projectVirtualFlowRows(steps: FlowStep[]): VirtualFlowRow[] {
  const rows: VirtualFlowRow[] = [];
  projectList(steps, 'steps', [], 0, [], rows);
  return rows;
}
