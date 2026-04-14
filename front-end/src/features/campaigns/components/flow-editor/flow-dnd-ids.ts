import type { FlowStep } from '../scenario-steps/types';

/** Stable id per step object for @dnd-kit (global across root + nested lists). */
const stepObjectDnDIds = new WeakMap<object, string>();

function newDnDStepId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `dnd-${crypto.randomUUID()}`;
  }
  return `dnd-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export function stableStepDnDId(step: FlowStep, _index: number): string {
  const raw = (step as { _id?: unknown })._id;
  if (typeof raw === 'string' && raw.length > 0) return raw;
  let id = stepObjectDnDIds.get(step);
  if (!id) {
    id = newDnDStepId();
    stepObjectDnDIds.set(step, id);
  }
  return id;
}

export type FlowListRef =
  | { kind: 'root' }
  | {
      kind: 'nested';
      rootIndex: number;
      pathToBracket: Array<{ listKey: string; childIndex: number }>;
      listKey: string;
    };

export function encodeFlowListRef(ref: FlowListRef): string {
  return JSON.stringify(ref);
}

export function decodeFlowListRef(id: string): FlowListRef | null {
  try {
    const o = JSON.parse(id) as unknown;
    if (!o || typeof o !== 'object') return null;
    const r = o as Record<string, unknown>;
    if (r.kind === 'root') return { kind: 'root' };
    if (
      r.kind === 'nested' &&
      typeof r.rootIndex === 'number' &&
      Array.isArray(r.pathToBracket) &&
      typeof r.listKey === 'string'
    ) {
      return {
        kind: 'nested',
        rootIndex: r.rootIndex,
        pathToBracket: r.pathToBracket as Array<{ listKey: string; childIndex: number }>,
        listKey: r.listKey,
      };
    }
  } catch {
    /* ignore */
  }
  return null;
}
