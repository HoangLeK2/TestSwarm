import type { FlowStep } from '../scenario-steps/types';

/** Path segment from root step into nested lists (then/else/steps/branches…). */
export type ScenarioStepPathSegment = { listKey: string; childIndex: number };

export type InlineRunState = 'idle' | 'running' | 'ok' | 'error';

/** Stable key for inline preview run state (root index + path to the step/block). */
export function encodeScenarioInlineRunKey(
  rootIndex: number,
  path: ScenarioStepPathSegment[]
): string {
  if (!path.length) return String(rootIndex);
  return `${rootIndex}/${path.map((p) => `${p.listKey}:${p.childIndex}`).join('/')}`;
}

export function decodeScenarioInlineRunKey(runKey: string): {
  rootIndex: number;
  path: ScenarioStepPathSegment[];
} | null {
  const trimmed = runKey.trim();
  if (!trimmed) return null;
  const slash = trimmed.indexOf('/');
  if (slash < 0) {
    const rootIndex = Number.parseInt(trimmed, 10);
    if (Number.isNaN(rootIndex)) return null;
    return { rootIndex, path: [] };
  }
  const rootIndex = Number.parseInt(trimmed.slice(0, slash), 10);
  if (Number.isNaN(rootIndex)) return null;
  const path: ScenarioStepPathSegment[] = [];
  for (const part of trimmed.slice(slash + 1).split('/')) {
    if (!part) continue;
    const colon = part.indexOf(':');
    if (colon <= 0) return null;
    const listKey = part.slice(0, colon);
    const childIndex = Number.parseInt(part.slice(colon + 1), 10);
    if (Number.isNaN(childIndex)) return null;
    path.push({ listKey, childIndex });
  }
  return { rootIndex, path };
}

/** Resolve the latest step snapshot for inline preview from `steps` + run key. */
export function resolveStepForInlineRunKey(
  steps: FlowStep[],
  runKey: string
): FlowStep | null {
  const decoded = decodeScenarioInlineRunKey(runKey);
  if (!decoded) return null;
  let node: FlowStep | null = steps[decoded.rootIndex] ?? null;
  for (const { listKey, childIndex } of decoded.path) {
    if (!node) return null;
    if (listKey.startsWith('branches.')) {
      const bi = Number.parseInt(listKey.split('.')[1] ?? '0', 10);
      node =
        (node as FlowStep & { branches?: Array<{ steps?: FlowStep[] }> })
          .branches?.[bi]?.steps?.[childIndex] ?? null;
    } else {
      node =
        ((node as Record<string, unknown>)[listKey] as FlowStep[])?.[
          childIndex
        ] ?? null;
    }
  }
  return node;
}

/** Live step tree wins over the StepCard snapshot captured at last render. */
export function resolveLatestStepForInlineRun(
  steps: FlowStep[],
  runKey: string,
  clickSnapshot: FlowStep
): FlowStep {
  return resolveStepForInlineRunKey(steps, runKey) ?? clickSnapshot;
}

type PreviewStepResult = {
  ok?: boolean;
  branch?: string;
  chosen_branch?: number;
  sub_result?: { step_results?: PreviewStepResult[] };
  sub_results?: Array<{ result?: { step_results?: PreviewStepResult[] } }>;
};

function appendInlineRunKey(runKey: string, listKey: string, childIndex: number) {
  return `${runKey}/${listKey}:${childIndex}`;
}

function nestedListKeyForResult(result: PreviewStepResult): string {
  if (typeof result.branch === 'string' && result.branch) {
    return result.branch;
  }
  if (typeof result.chosen_branch === 'number') {
    return `branches.${result.chosen_branch}.steps`;
  }
  return 'steps';
}

function collectNestedStates(
  runKey: string,
  result: PreviewStepResult,
  out: Record<string, InlineRunState>
) {
  const directChildren = result.sub_result?.step_results;
  if (Array.isArray(directChildren)) {
    const listKey = nestedListKeyForResult(result);
    directChildren.forEach((child, childIndex) => {
      const childKey = appendInlineRunKey(runKey, listKey, childIndex);
      out[childKey] = child.ok === false ? 'error' : 'ok';
      collectNestedStates(childKey, child, out);
    });
  }

  for (const entry of result.sub_results ?? []) {
    const iterChildren = entry.result?.step_results;
    if (!Array.isArray(iterChildren)) continue;
    iterChildren.forEach((child, childIndex) => {
      const childKey = appendInlineRunKey(runKey, 'steps', childIndex);
      out[childKey] = child.ok === false ? 'error' : 'ok';
      collectNestedStates(childKey, child, out);
    });
  }
}

export function deriveNestedInlineRunStates(
  runKey: string,
  event: PreviewStepResult & { event?: string }
): Record<string, InlineRunState> {
  if (event.event !== 'step_done') return {};
  const out: Record<string, InlineRunState> = {};
  collectNestedStates(runKey, event, out);
  return out;
}
