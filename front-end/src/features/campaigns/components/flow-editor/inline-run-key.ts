import type { FlowStep } from '../scenario-steps/types';

/** Path segment from root step into nested lists (then/else/steps/branches…). */
export type ScenarioStepPathSegment = { listKey: string; childIndex: number };

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
        (
          node as FlowStep & { branches?: Array<{ steps?: FlowStep[] }> }
        ).branches?.[bi]?.steps?.[childIndex] ?? null;
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
