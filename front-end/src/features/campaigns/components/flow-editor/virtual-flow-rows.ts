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
      label: string;
      count: number;
      depth: number;
      scopes: VirtualFlowScope[];
    }
  | {
      kind: 'end';
      key: string;
      label: string;
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
    step.type === 'fb_tap_comment_button' ||
    step.type === 'tap_fb_comment_button'
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
        label: 'NỘI DUNG LẶP',
        count: body.length,
        depth: depth + 1,
        scopes: nestedScopes
      });
      projectList(body, 'steps', path, depth + 1, nestedScopes, rows);
      rows.push({
        kind: 'end',
        key: `end:${ownerKey}`,
        label: 'KẾT THÚC VÒNG LẶP',
        depth,
        scopes: nestedScopes
      });
      return;
    }

    if (isConditional(step)) {
      const isFbTap =
        step.type === 'fb_tap_comment_button' ||
        step.type === 'tap_fb_comment_button';
      const thenSteps = step.then ?? [];
      const elseSteps = step.else ?? [];
      rows.push({
        kind: 'branch',
        key: `branch:${ownerKey}:then`,
        label: isFbTap ? 'KHI TÌM THẤY' : 'NẾU ĐÚNG',
        count: thenSteps.length,
        depth: depth + 1,
        scopes: nestedScopes
      });
      projectList(thenSteps, 'then', path, depth + 1, nestedScopes, rows);
      rows.push({
        kind: 'branch',
        key: `branch:${ownerKey}:else`,
        label: isFbTap ? 'KHI KHÔNG TÌM THẤY' : 'NẾU SAI',
        count: elseSteps.length,
        depth: depth + 1,
        scopes: nestedScopes
      });
      projectList(elseSteps, 'else', path, depth + 1, nestedScopes, rows);
      rows.push({
        kind: 'end',
        key: `end:${ownerKey}`,
        label: 'KẾT THÚC IF',
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
          label: `NHÁNH ${branchIndex + 1}`,
          count: branchSteps.length,
          depth: depth + 1,
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
        label: 'KẾT THÚC CHỌN NHÁNH',
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
