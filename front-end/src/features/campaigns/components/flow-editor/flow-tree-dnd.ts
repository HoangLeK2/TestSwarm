import type { DragEndEvent } from '@dnd-kit/core';
import { arrayMove } from '@dnd-kit/sortable';
import { isControlFlow, type FlowStep } from '../scenario-steps/types';
import {
  decodeFlowListRef,
  type FlowListRef,
  stableStepDnDId
} from './flow-dnd-ids';

function readListKeyFromNode(node: FlowStep, listKey: string): FlowStep[] {
  if (listKey.startsWith('branches.')) {
    const m = listKey.match(/^branches\.(\d+)\.steps$/);
    if (!m) return [];
    const bi = parseInt(m[1]!, 10);
    return ((node as { branches?: Array<{ steps?: FlowStep[] }> }).branches?.[
      bi
    ]?.steps ?? []) as FlowStep[];
  }
  return (
    ((node as Record<string, unknown>)[listKey] as FlowStep[] | undefined) ?? []
  );
}

function setListKeyOnNode(
  node: FlowStep,
  listKey: string,
  newList: FlowStep[]
): FlowStep {
  if (listKey.startsWith('branches.')) {
    const m = listKey.match(/^branches\.(\d+)\.steps$/);
    if (!m) return node;
    const bi = parseInt(m[1]!, 10);
    const branches = [
      ...(((node as { branches?: unknown[] }).branches ?? []) as object[])
    ];
    const cur = (branches[bi] ?? {}) as { steps?: FlowStep[]; weight?: number };
    branches[bi] = { ...cur, steps: newList };
    return { ...node, branches } as FlowStep;
  }
  return { ...node, [listKey]: newList } as FlowStep;
}

function replaceInStep(
  step: FlowStep,
  path: Array<{ listKey: string; childIndex: number }>,
  listKey: string,
  newList: FlowStep[]
): FlowStep {
  if (path.length === 0) {
    return setListKeyOnNode(step, listKey, newList);
  }
  const [head, ...rest] = path;
  const arr = [...readListKeyFromNode(step, head.listKey)];
  arr[head.childIndex] = replaceInStep(
    arr[head.childIndex]!,
    rest,
    listKey,
    newList
  );
  return setListKeyOnNode(step, head.listKey, arr);
}

export function readFlowList(steps: FlowStep[], ref: FlowListRef): FlowStep[] {
  if (ref.kind === 'root') return steps;
  const root = steps[ref.rootIndex];
  if (!root) return [];
  let node: FlowStep = root;
  for (const seg of ref.pathToBracket) {
    const arr = readListKeyFromNode(node, seg.listKey);
    node = arr[seg.childIndex]!;
    if (!node) return [];
  }
  return readListKeyFromNode(node, ref.listKey);
}

export function writeFlowList(
  steps: FlowStep[],
  ref: Extract<FlowListRef, { kind: 'nested' }>,
  newList: FlowStep[]
): FlowStep[] {
  const next = [...steps];
  const root = next[ref.rootIndex];
  if (!root) return steps;
  next[ref.rootIndex] = replaceInStep(
    root,
    ref.pathToBracket,
    ref.listKey,
    newList
  );
  return next;
}

function tryRemoveFromStep(
  step: FlowStep,
  dragId: string
): { step: FlowStep; removed: FlowStep } | null {
  const tryList = (
    listKey: string,
    arr: FlowStep[]
  ): { step: FlowStep; removed: FlowStep } | null => {
    const idx = arr.findIndex((s, i) => stableStepDnDId(s, i) === dragId);
    if (idx < 0) return null;
    const removed = arr[idx]!;
    const newArr = arr.filter((_, i) => i !== idx);
    return { step: setListKeyOnNode(step, listKey, newArr), removed };
  };

  const sx = step as unknown as Record<string, unknown>;
  if (Array.isArray(sx.steps)) {
    const r = tryList('steps', sx.steps as FlowStep[]);
    if (r) return r;
  }
  if (Array.isArray(sx.then)) {
    const r = tryList('then', sx.then as FlowStep[]);
    if (r) return r;
  }
  if (Array.isArray(sx.else)) {
    const r = tryList('else', sx.else as FlowStep[]);
    if (r) return r;
  }
  const branches = (step as { branches?: Array<{ steps?: FlowStep[] }> })
    .branches;
  if (Array.isArray(branches)) {
    for (let bi = 0; bi < branches.length; bi++) {
      const bSteps = branches[bi]?.steps;
      if (!Array.isArray(bSteps)) continue;
      const idx = bSteps.findIndex((s, i) => stableStepDnDId(s, i) === dragId);
      if (idx >= 0) {
        const removed = bSteps[idx]!;
        const nb = [...branches];
        nb[bi] = { ...nb[bi]!, steps: bSteps.filter((_, i) => i !== idx) };
        return { step: { ...step, branches: nb } as FlowStep, removed };
      }
    }
  }

  const recurseInto = (
    listKey: string,
    arr: FlowStep[]
  ): { step: FlowStep; removed: FlowStep } | null => {
    const nextArr = [...arr];
    for (let i = 0; i < nextArr.length; i++) {
      const ch = nextArr[i]!;
      if (!isControlFlow(ch.type)) continue;
      const inner = tryRemoveFromStep(ch, dragId);
      if (inner) {
        nextArr[i] = inner.step;
        return {
          step: setListKeyOnNode(step, listKey, nextArr),
          removed: inner.removed
        };
      }
    }
    return null;
  };

  if (Array.isArray(sx.steps)) {
    const r = recurseInto('steps', sx.steps as FlowStep[]);
    if (r) return r;
  }
  if (Array.isArray(sx.then)) {
    const r = recurseInto('then', sx.then as FlowStep[]);
    if (r) return r;
  }
  if (Array.isArray(sx.else)) {
    const r = recurseInto('else', sx.else as FlowStep[]);
    if (r) return r;
  }
  if (Array.isArray(branches)) {
    for (let bi = 0; bi < branches.length; bi++) {
      const bSteps = branches[bi]?.steps;
      if (!Array.isArray(bSteps)) continue;
      const nextArr = [...bSteps];
      for (let i = 0; i < nextArr.length; i++) {
        const ch = nextArr[i]!;
        if (!isControlFlow(ch.type)) continue;
        const inner = tryRemoveFromStep(ch, dragId);
        if (inner) {
          nextArr[i] = inner.step;
          const nb = [...branches];
          nb[bi] = { ...nb[bi]!, steps: nextArr };
          return {
            step: { ...step, branches: nb } as FlowStep,
            removed: inner.removed
          };
        }
      }
    }
  }

  return null;
}

/** Remove first step whose stable id matches (DFS). Returns unchanged steps if not found. */
export function removeStepByDragId(
  steps: FlowStep[],
  dragId: string
): { steps: FlowStep[]; removed: FlowStep | null } {
  const ri = steps.findIndex((s, i) => stableStepDnDId(s, i) === dragId);
  if (ri >= 0) {
    const removed = steps[ri]!;
    return { steps: steps.filter((_, i) => i !== ri), removed };
  }
  const next = [...steps];
  for (let i = 0; i < next.length; i++) {
    const s = next[i]!;
    if (!isControlFlow(s.type)) continue;
    const hit = tryRemoveFromStep(s, dragId);
    if (hit) {
      next[i] = hit.step;
      return { steps: next, removed: hit.removed };
    }
  }
  return { steps, removed: null };
}

export function insertStepInList(
  steps: FlowStep[],
  ref: FlowListRef,
  index: number,
  step: FlowStep
): FlowStep[] {
  if (ref.kind === 'root') {
    const arr = [...steps];
    arr.splice(Math.max(0, Math.min(index, arr.length)), 0, step);
    return arr;
  }
  const cur = readFlowList(steps, ref);
  const arr = [...cur];
  arr.splice(Math.max(0, Math.min(index, arr.length)), 0, step);
  return writeFlowList(steps, ref, arr);
}

type StepPathSegment = { listKey: string; childIndex: number };

function samePath(a: StepPathSegment[], b: StepPathSegment[]): boolean {
  return (
    a.length === b.length &&
    a.every(
      (seg, i) =>
        seg.listKey === b[i]?.listKey && seg.childIndex === b[i]?.childIndex
    )
  );
}

function flowListOwnerPath(ref: FlowListRef): StepPathSegment[] {
  if (ref.kind === 'root') return [];
  return [
    { listKey: 'steps', childIndex: ref.rootIndex },
    ...ref.pathToBracket
  ];
}

function flowListRefFromOwnerPath(
  ref: FlowListRef,
  ownerPath: StepPathSegment[]
): FlowListRef | null {
  if (ref.kind === 'root') return ref;
  const [root, ...pathToBracket] = ownerPath;
  if (!root || root.listKey !== 'steps') return null;
  return {
    kind: 'nested',
    rootIndex: root.childIndex,
    pathToBracket,
    listKey: ref.listKey
  };
}

function sourceListLocation(
  ref: FlowListRef,
  sourceIndex: number
): {
  parentPath: StepPathSegment[];
  listKey: string;
  sourcePath: StepPathSegment[];
} {
  if (ref.kind === 'root') {
    return {
      parentPath: [],
      listKey: 'steps',
      sourcePath: [{ listKey: 'steps', childIndex: sourceIndex }]
    };
  }
  const parentPath = flowListOwnerPath(ref);
  return {
    parentPath,
    listKey: ref.listKey,
    sourcePath: [
      ...parentPath,
      { listKey: ref.listKey, childIndex: sourceIndex }
    ]
  };
}

function isDescendantPath(
  path: StepPathSegment[],
  ancestor: StepPathSegment[]
): boolean {
  return (
    path.length >= ancestor.length &&
    ancestor.every(
      (seg, i) =>
        seg.listKey === path[i]?.listKey &&
        seg.childIndex === path[i]?.childIndex
    )
  );
}

function adjustOwnerPathAfterRemoval(
  ownerPath: StepPathSegment[],
  sourceParentPath: StepPathSegment[],
  sourceListKey: string,
  sourceIndex: number
): StepPathSegment[] | null {
  if (ownerPath.length === 0) return ownerPath;
  const next = ownerPath.map((seg) => ({ ...seg }));

  for (let i = 0; i < next.length; i++) {
    const parentPath = next.slice(0, i);
    const seg = next[i]!;
    if (
      !samePath(parentPath, sourceParentPath) ||
      seg.listKey !== sourceListKey
    ) {
      continue;
    }
    if (seg.childIndex === sourceIndex) return null;
    if (seg.childIndex > sourceIndex) {
      seg.childIndex -= 1;
    }
    break;
  }

  return next;
}

function adjustFlowListRefAfterRemoval(
  ref: FlowListRef,
  sourceRef: FlowListRef,
  sourceIndex: number
): FlowListRef | null {
  if (ref.kind === 'root') return ref;

  const ownerPath = flowListOwnerPath(ref);
  const source = sourceListLocation(sourceRef, sourceIndex);
  if (isDescendantPath(ownerPath, source.sourcePath)) return null;

  const adjustedOwnerPath = adjustOwnerPathAfterRemoval(
    ownerPath,
    source.parentPath,
    source.listKey,
    sourceIndex
  );
  if (!adjustedOwnerPath) return null;
  return flowListRefFromOwnerPath(ref, adjustedOwnerPath);
}

export function applyFlowDragEnd(
  event: DragEndEvent,
  steps: FlowStep[],
  onChange: (next: FlowStep[]) => void
): void {
  const { active, over } = event;
  if (!over) return;

  const activeContainer = active.data.current?.sortable?.containerId as
    | string
    | undefined;
  const overContainer = (over.data.current?.sortable?.containerId ??
    over.data.current?.flowListContainerId) as string | undefined;
  if (!activeContainer || !overContainer) return;

  const activeRef = decodeFlowListRef(activeContainer);
  const overRef = decodeFlowListRef(overContainer);
  if (!activeRef || !overRef) return;

  if (active.id === over.id && activeContainer === overContainer) return;

  const dragId = String(active.id);

  if (activeContainer === overContainer) {
    const list = readFlowList(steps, activeRef);
    const ids = list.map((s, i) => stableStepDnDId(s, i));
    const oldIndex = ids.indexOf(dragId);
    const newIndex = ids.indexOf(String(over.id));
    if (oldIndex < 0 || newIndex < 0 || oldIndex === newIndex) return;
    const moved = arrayMove(list, oldIndex, newIndex);
    if (activeRef.kind === 'root') {
      onChange(moved);
    } else {
      onChange(writeFlowList(steps, activeRef, moved));
    }
    return;
  }

  const { steps: without, removed } = removeStepByDragId(steps, dragId);
  if (!removed) return;

  const sourceList = readFlowList(steps, activeRef);
  const sourceIds = sourceList.map((s, i) => stableStepDnDId(s, i));
  const sourceIndex = sourceIds.indexOf(dragId);
  if (sourceIndex < 0) return;

  const adjustedOverRef = adjustFlowListRefAfterRemoval(
    overRef,
    activeRef,
    sourceIndex
  );
  if (!adjustedOverRef) return;

  const overList = readFlowList(without, adjustedOverRef);
  const overIds = overList.map((s, i) => stableStepDnDId(s, i));
  let insertIndex = overIds.indexOf(String(over.id));
  if (insertIndex < 0) {
    insertIndex = overList.length;
  }

  const next = insertStepInList(without, adjustedOverRef, insertIndex, removed);
  onChange(next);
}
