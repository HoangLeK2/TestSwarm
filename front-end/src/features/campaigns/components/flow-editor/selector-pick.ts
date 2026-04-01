import type { FlowStep } from '../scenario-steps/types';

/** Identifies a step that uses resource/text selectors (for pick-from-device). */
export const SELECTOR_STEP_TYPES = new Set([
  'tap',           // recorded tap — selector nested in step.selector
  'tap_selector',
  'long_tap_selector',
  'input_selector',
  'wait_element',
  'assert_element',
  'scroll_to',
  'if_element',
]);

/**
 * Unified selector pick target using a root index + path array.
 *
 * - `path = []`                          → update the root step itself (e.g. if_element condition)
 * - `path = [{ listKey, childIndex }]`   → update a direct child (1-level nesting)
 * - longer paths                         → arbitrary deep nesting
 */
export type SelectorPickTarget = {
  rootIndex: number;
  path: Array<{ listKey: string; childIndex: number }>;
};

export function selectorPickTargetEquals(
  a: SelectorPickTarget | null | undefined,
  b: SelectorPickTarget | null | undefined,
): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  if (a.rootIndex !== b.rootIndex) return false;
  const ap = a.path ?? [];
  const bp = b.path ?? [];
  if (ap.length !== bp.length) return false;
  return ap.every((seg, i) => seg.listKey === bp[i]!.listKey && seg.childIndex === bp[i]!.childIndex);
}

function mergeSelector(step: FlowStep, by: string, value: string): FlowStep {
  // 'tap' stores selector nested: step.selector = { by, value }
  if (step.type === 'tap') {
    return { ...step, selector: { by, value } };
  }
  return { ...step, by, value };
}

/**
 * Apply uiautomator2 selector to the step identified by `target`.
 * Returns the same `steps` reference if nothing changed.
 */
export function applySelectorToSteps(
  steps: FlowStep[],
  target: SelectorPickTarget,
  by: string,
  value: string,
): FlowStep[] {
  const root = steps[target.rootIndex];
  if (!root) return steps;
  const targetPath = target.path ?? [];

  function applyAtPath(node: FlowStep, pathIdx: number): FlowStep {
    if (pathIdx === targetPath.length) {
      // This IS the node to update
      if (!SELECTOR_STEP_TYPES.has(node.type)) return node;
      return mergeSelector(node, by, value);
    }

    const seg = targetPath[pathIdx]!;
    const { listKey, childIndex } = seg;

    if (listKey.startsWith('branches.')) {
      const bi = parseInt(listKey.split('.')[1] ?? '0', 10);
      const branches = [...((node.branches as any[]) ?? [])];
      const b = branches[bi];
      if (!b) return node;
      const stepsArr = [...(b.steps ?? [])];
      const child = stepsArr[childIndex];
      if (!child) return node;
      const updatedChild = applyAtPath(child, pathIdx + 1);
      if (updatedChild === child) return node;
      stepsArr[childIndex] = updatedChild;
      branches[bi] = { ...b, steps: stepsArr };
      return { ...node, branches };
    }

    const arr = [...(((node as Record<string, unknown>)[listKey] as FlowStep[]) ?? [])];
    const child = arr[childIndex];
    if (!child) return node;
    const updatedChild = applyAtPath(child, pathIdx + 1);
    if (updatedChild === child) return node;
    arr[childIndex] = updatedChild;
    return { ...node, [listKey]: arr };
  }

  const updated = applyAtPath(root, 0);
  if (updated === root) return steps;
  const next = [...steps];
  next[target.rootIndex] = updated;
  return next;
}

export function isSelectorPickableStep(step: FlowStep): boolean {
  return SELECTOR_STEP_TYPES.has(step.type);
}
