import type { FlowStep } from '../scenario-steps/types';

/** Pick tap_ratio / tap fallback / swipe_ratio from device mirror (same path model as selector pick). */
export type CoordinatePickTarget = {
  rootIndex: number;
  path: Array<{ listKey: string; childIndex: number }>;
  mode: 'tap_point' | 'swipe_segment';
};

export function coordinatePickTargetEquals(
  a: CoordinatePickTarget | null | undefined,
  b: CoordinatePickTarget | null | undefined
): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  if (a.rootIndex !== b.rootIndex || a.mode !== b.mode) return false;
  const ap = a.path ?? [];
  const bp = b.path ?? [];
  if (ap.length !== bp.length) return false;
  return ap.every(
    (seg, i) =>
      seg.listKey === bp[i]!.listKey && seg.childIndex === bp[i]!.childIndex
  );
}

function mergeTapPointLeaf(step: FlowStep, rx: number, ry: number): FlowStep {
  const x = parseFloat(rx.toFixed(3));
  const y = parseFloat(ry.toFixed(3));
  if (step.type === 'tap_ratio') return { ...step, x, y };
  if (step.type === 'tap') {
    return {
      ...step,
      fallback: {
        ...((step.fallback as Record<string, number> | undefined) ?? {}),
        rx: x,
        ry: y
      }
    };
  }
  return step;
}

function mergeSwipeLeaf(
  step: FlowStep,
  rx1: number,
  ry1: number,
  rx2: number,
  ry2: number,
  durationMs: number
): FlowStep {
  if (step.type !== 'swipe_ratio') return step;
  return {
    ...step,
    x1: parseFloat(rx1.toFixed(3)),
    y1: parseFloat(ry1.toFixed(3)),
    x2: parseFloat(rx2.toFixed(3)),
    y2: parseFloat(ry2.toFixed(3)),
    duration_ms: Math.round(Math.max(100, Math.min(durationMs, 2000)))
  };
}

/** Apply normalized tap point (0–1) to tap_ratio or tap.fallback at target. */
export function applyTapPointToSteps(
  steps: FlowStep[],
  target: CoordinatePickTarget,
  rx: number,
  ry: number
): FlowStep[] {
  if (target.mode !== 'tap_point') return steps;
  const root = steps[target.rootIndex];
  if (!root) return steps;

  function applyAtPath(node: FlowStep, pathIdx: number): FlowStep {
    if (pathIdx === (target.path ?? []).length) {
      const merged = mergeTapPointLeaf(node, rx, ry);
      return merged === node ? node : merged;
    }
    const seg = target.path![pathIdx]!;
    const { listKey, childIndex } = seg;

    if (listKey.startsWith('branches.')) {
      const bi = parseInt(listKey.split('.')[1] ?? '0', 10);
      const branches = [...((node.branches as FlowStep[]) ?? [])];
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

    const arr = [
      ...(((node as Record<string, unknown>)[listKey] as FlowStep[]) ?? [])
    ];
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

/** Apply swipe segment (normalized 0–1) to swipe_ratio at target. */
export function applySwipeSegmentToSteps(
  steps: FlowStep[],
  target: CoordinatePickTarget,
  rx1: number,
  ry1: number,
  rx2: number,
  ry2: number,
  durationMs: number
): FlowStep[] {
  if (target.mode !== 'swipe_segment') return steps;
  const root = steps[target.rootIndex];
  if (!root) return steps;

  function applyAtPath(node: FlowStep, pathIdx: number): FlowStep {
    if (pathIdx === (target.path ?? []).length) {
      const merged = mergeSwipeLeaf(node, rx1, ry1, rx2, ry2, durationMs);
      return merged === node ? node : merged;
    }
    const seg = target.path![pathIdx]!;
    const { listKey, childIndex } = seg;

    if (listKey.startsWith('branches.')) {
      const bi = parseInt(listKey.split('.')[1] ?? '0', 10);
      const branches = [...((node.branches as FlowStep[]) ?? [])];
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

    const arr = [
      ...(((node as Record<string, unknown>)[listKey] as FlowStep[]) ?? [])
    ];
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

export function isTapCoordinatePickableStep(step: FlowStep): boolean {
  return step.type === 'tap_ratio' || step.type === 'tap';
}

export function isSwipeCoordinatePickableStep(step: FlowStep): boolean {
  return step.type === 'swipe_ratio';
}
