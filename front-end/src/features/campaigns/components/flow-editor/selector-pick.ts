import type { FlowStep } from '../scenario-steps/types';

/** Identifies a step that uses resource/text selectors (for pick-from-device). */
export const SELECTOR_STEP_TYPES = new Set([
  'tap_selector',
  'long_tap_selector',
  'input_selector',
  'wait_element',
  'assert_element',
  'scroll_to',
  'if_element',
]);

export type SelectorPickTarget =
  | { kind: 'root'; index: number }
  | { kind: 'child'; parentIndex: number; listKey: string; childIndex: number };

export function selectorPickTargetEquals(
  a: SelectorPickTarget | null | undefined,
  b: SelectorPickTarget | null | undefined,
): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  if (a.kind !== b.kind) return false;
  if (a.kind === 'root') return b.kind === 'root' && a.index === b.index;
  return (
    b.kind === 'child' &&
    a.parentIndex === b.parentIndex &&
    a.listKey === b.listKey &&
    a.childIndex === b.childIndex
  );
}

function mergeSelector(step: FlowStep, by: string, value: string): FlowStep {
  return { ...step, by, value };
}

function applyToChildParent(
  parent: FlowStep,
  listKey: string,
  childIndex: number,
  by: string,
  value: string,
): FlowStep {
  if (listKey.startsWith('branches.')) {
    const bi = parseInt(listKey.split('.')[1] ?? '0', 10);
    const branches = [...(parent.branches ?? [])];
    const b = branches[bi];
    if (!b) return parent;
    const stepsArr = [...(b.steps ?? [])];
    const ch = stepsArr[childIndex];
    if (!ch || !SELECTOR_STEP_TYPES.has(ch.type)) return parent;
    stepsArr[childIndex] = mergeSelector(ch, by, value);
    branches[bi] = { ...b, steps: stepsArr };
    return { ...parent, branches };
  }
  const arr = [...(((parent as Record<string, unknown>)[listKey] as FlowStep[]) ?? [])];
  const ch = arr[childIndex];
  if (!ch || !SELECTOR_STEP_TYPES.has(ch.type)) return parent;
  arr[childIndex] = mergeSelector(ch, by, value);
  return { ...parent, [listKey]: arr };
}

/** Apply uiautomator2 selector to the step at `target`. Returns same reference if nothing changed. */
export function applySelectorToSteps(
  steps: FlowStep[],
  target: SelectorPickTarget,
  by: string,
  value: string,
): FlowStep[] {
  if (target.kind === 'root') {
    const s = steps[target.index];
    if (!s || !SELECTOR_STEP_TYPES.has(s.type)) return steps;
    const next = [...steps];
    next[target.index] = mergeSelector(s, by, value);
    return next;
  }
  const parent = steps[target.parentIndex];
  if (!parent) return steps;
  const updated = applyToChildParent(parent, target.listKey, target.childIndex, by, value);
  if (updated === parent) return steps;
  const next = [...steps];
  next[target.parentIndex] = updated;
  return next;
}

export function isSelectorPickableStep(step: FlowStep): boolean {
  return SELECTOR_STEP_TYPES.has(step.type);
}
