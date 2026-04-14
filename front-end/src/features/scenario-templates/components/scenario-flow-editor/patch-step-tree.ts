/**
 * Mutate nested FlowStep trees by stable flowgram node id (_fgId).
 */
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { SELECTOR_STEP_TYPES } from '@/features/campaigns/components/flow-editor/selector-pick';

const FG = '_fgId' as const;

export function patchStepByFlowgramId(steps: FlowStep[], fgId: string, replacement: FlowStep): FlowStep[] {
  return steps.map((s) => patchOne(s, fgId, replacement));
}

function patchOne(s: FlowStep, fgId: string, replacement: FlowStep): FlowStep {
  if ((s as Record<string, unknown>)[FG] === fgId) {
    return { ...replacement, [FG]: fgId } as FlowStep;
  }
  const t = s.type;
  if (t === 'if_element' || t === 'if_variable') {
    const cur = s as FlowStep & { then?: FlowStep[]; else?: FlowStep[] };
    return {
      ...s,
      then: patchArray(cur.then ?? [], fgId, replacement),
      else: patchArray(cur.else ?? [], fgId, replacement),
    } as FlowStep;
  }
  if (t === 'random_pick') {
    const cur = s as FlowStep & { branches?: Array<{ weight?: number; steps?: FlowStep[] }> };
    return {
      ...s,
      branches: (cur.branches ?? []).map((br) => ({
        ...br,
        steps: patchArray(br.steps ?? [], fgId, replacement),
      })),
    } as FlowStep;
  }
  if (t === 'repeat' || t === 'repeat_until' || t === 'loop') {
    const cur = s as FlowStep & { steps?: FlowStep[] };
    return {
      ...s,
      steps: patchArray(cur.steps ?? [], fgId, replacement),
    } as FlowStep;
  }
  return s;
}

function patchArray(arr: FlowStep[], fgId: string, replacement: FlowStep): FlowStep[] {
  return arr.map((x) => patchOne(x, fgId, replacement));
}

/** Merge fields into the step that matches fgId (shallow merge for coord/selector tweaks). */
export function mergeStepByFlowgramId(
  steps: FlowStep[],
  fgId: string,
  patch: Partial<FlowStep> | ((prev: FlowStep) => FlowStep),
): FlowStep[] {
  return steps.map((s) => mergeOne(s, fgId, patch));
}

function mergeOne(s: FlowStep, fgId: string, patch: Partial<FlowStep> | ((prev: FlowStep) => FlowStep)): FlowStep {
  if ((s as Record<string, unknown>)[FG] === fgId) {
    const next = typeof patch === 'function' ? patch(s) : { ...s, ...patch };
    return { ...next, [FG]: fgId } as FlowStep;
  }
  const t = s.type;
  if (t === 'if_element' || t === 'if_variable') {
    const cur = s as FlowStep & { then?: FlowStep[]; else?: FlowStep[] };
    return {
      ...s,
      then: mergeArray(cur.then ?? [], fgId, patch),
      else: mergeArray(cur.else ?? [], fgId, patch),
    } as FlowStep;
  }
  if (t === 'random_pick') {
    const cur = s as FlowStep & { branches?: Array<{ weight?: number; steps?: FlowStep[] }> };
    return {
      ...s,
      branches: (cur.branches ?? []).map((br) => ({
        ...br,
        steps: mergeArray(br.steps ?? [], fgId, patch),
      })),
    } as FlowStep;
  }
  if (t === 'repeat' || t === 'repeat_until' || t === 'loop') {
    const cur = s as FlowStep & { steps?: FlowStep[] };
    return {
      ...s,
      steps: mergeArray(cur.steps ?? [], fgId, patch),
    } as FlowStep;
  }
  return s;
}

function mergeArray(arr: FlowStep[], fgId: string, patch: Partial<FlowStep> | ((prev: FlowStep) => FlowStep)): FlowStep[] {
  return arr.map((x) => mergeOne(x, fgId, patch));
}

function mergeSelectorOntoStep(step: FlowStep, by: string, value: string): FlowStep {
  if (step.type === 'tap') {
    return { ...step, selector: { by, value } } as FlowStep;
  }
  return { ...step, by, value } as FlowStep;
}

/** Apply mirror-picked selector to the step with this flowgram node id (shallow selector fields only). */
export function mergeSelectorByFlowgramId(steps: FlowStep[], fgId: string, by: string, value: string): FlowStep[] {
  return mergeStepByFlowgramId(steps, fgId, (prev) => {
    if (!SELECTOR_STEP_TYPES.has(prev.type)) return prev;
    return mergeSelectorOntoStep(prev, by, value);
  });
}

export function findStepByFlowgramId(steps: FlowStep[], fgId: string): FlowStep | null {
  for (const s of steps) {
    const hit = findOneDeep(s, fgId);
    if (hit) return hit;
  }
  return null;
}

function findOneDeep(s: FlowStep, fgId: string): FlowStep | null {
  if ((s as Record<string, unknown>)[FG] === fgId) return s;
  const t = s.type;
  if (t === 'if_element' || t === 'if_variable') {
    const cur = s as FlowStep & { then?: FlowStep[]; else?: FlowStep[] };
    for (const x of cur.then ?? []) {
      const h = findOneDeep(x, fgId);
      if (h) return h;
    }
    for (const x of cur.else ?? []) {
      const h = findOneDeep(x, fgId);
      if (h) return h;
    }
  } else if (t === 'random_pick') {
    const cur = s as FlowStep & { branches?: Array<{ steps?: FlowStep[] }> };
    for (const br of cur.branches ?? []) {
      for (const x of br.steps ?? []) {
        const h = findOneDeep(x, fgId);
        if (h) return h;
      }
    }
  } else if (t === 'repeat' || t === 'repeat_until' || t === 'loop') {
    const cur = s as FlowStep & { steps?: FlowStep[] };
    for (const x of cur.steps ?? []) {
      const h = findOneDeep(x, fgId);
      if (h) return h;
    }
  }
  return null;
}
