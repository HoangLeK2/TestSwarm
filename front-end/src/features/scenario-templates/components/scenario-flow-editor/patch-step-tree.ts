/**
 * Mutate nested FlowStep trees by stable flowgram node id (_fgId).
 */
import type { FlowStep } from '../../../campaigns/components/scenario-steps/types';
import { SELECTOR_STEP_TYPES } from '../../../campaigns/components/flow-editor/selector-pick';

const FG = '_fgId' as const;

export function patchStepByFlowgramId(
  steps: FlowStep[],
  fgId: string,
  replacement: FlowStep
): FlowStep[] {
  return steps.map((s) => patchOne(s, fgId, replacement));
}

function hasThenElseBranches(type: string): boolean {
  return (
    type === 'if_element' ||
    type === 'if_variable' ||
    type === 'tap_fb_comment_button' ||
    type === 'fb_tap_comment_button'
  );
}

function patchOne(s: FlowStep, fgId: string, replacement: FlowStep): FlowStep {
  if ((s as Record<string, unknown>)[FG] === fgId) {
    return { ...replacement, [FG]: fgId } as FlowStep;
  }
  const t = s.type;
  if (hasThenElseBranches(t)) {
    const cur = s as FlowStep & { then?: FlowStep[]; else?: FlowStep[] };
    return {
      ...s,
      then: patchArray(cur.then ?? [], fgId, replacement),
      else: patchArray(cur.else ?? [], fgId, replacement)
    } as FlowStep;
  }
  if (t === 'random_pick') {
    const cur = s as FlowStep & {
      branches?: Array<{ weight?: number; steps?: FlowStep[] }>;
    };
    return {
      ...s,
      branches: (cur.branches ?? []).map((br) => ({
        ...br,
        steps: patchArray(br.steps ?? [], fgId, replacement)
      }))
    } as FlowStep;
  }
  if (t === 'repeat' || t === 'repeat_until' || t === 'loop') {
    const cur = s as FlowStep & { steps?: FlowStep[] };
    return {
      ...s,
      steps: patchArray(cur.steps ?? [], fgId, replacement)
    } as FlowStep;
  }
  return s;
}

function patchArray(
  arr: FlowStep[],
  fgId: string,
  replacement: FlowStep
): FlowStep[] {
  return arr.map((x) => patchOne(x, fgId, replacement));
}

/** Merge fields into the step that matches fgId (shallow merge for coord/selector tweaks). */
export function mergeStepByFlowgramId(
  steps: FlowStep[],
  fgId: string,
  patch: Partial<FlowStep> | ((prev: FlowStep) => FlowStep)
): FlowStep[] {
  return steps.map((s) => mergeOne(s, fgId, patch));
}

function mergeOne(
  s: FlowStep,
  fgId: string,
  patch: Partial<FlowStep> | ((prev: FlowStep) => FlowStep)
): FlowStep {
  if ((s as Record<string, unknown>)[FG] === fgId) {
    const next = typeof patch === 'function' ? patch(s) : { ...s, ...patch };
    return { ...next, [FG]: fgId } as FlowStep;
  }
  const t = s.type;
  if (hasThenElseBranches(t)) {
    const cur = s as FlowStep & { then?: FlowStep[]; else?: FlowStep[] };
    return {
      ...s,
      then: mergeArray(cur.then ?? [], fgId, patch),
      else: mergeArray(cur.else ?? [], fgId, patch)
    } as FlowStep;
  }
  if (t === 'random_pick') {
    const cur = s as FlowStep & {
      branches?: Array<{ weight?: number; steps?: FlowStep[] }>;
    };
    return {
      ...s,
      branches: (cur.branches ?? []).map((br) => ({
        ...br,
        steps: mergeArray(br.steps ?? [], fgId, patch)
      }))
    } as FlowStep;
  }
  if (t === 'repeat' || t === 'repeat_until' || t === 'loop') {
    const cur = s as FlowStep & { steps?: FlowStep[] };
    return {
      ...s,
      steps: mergeArray(cur.steps ?? [], fgId, patch)
    } as FlowStep;
  }
  return s;
}

function mergeArray(
  arr: FlowStep[],
  fgId: string,
  patch: Partial<FlowStep> | ((prev: FlowStep) => FlowStep)
): FlowStep[] {
  return arr.map((x) => mergeOne(x, fgId, patch));
}

function mergeSelectorOntoStep(
  step: FlowStep,
  pick: {
    by: string;
    value: string;
    conditions?: Record<string, unknown>;
    instance?: number;
  }
): FlowStep {
  const { by, value } = pick;
  const selector = {
    by,
    value,
    ...(pick.conditions && Object.keys(pick.conditions).length > 0
      ? { conditions: pick.conditions }
      : {}),
    ...(pick.instance != null ? { instance: pick.instance } : {})
  };
  if (step.type === 'tap') {
    return { ...step, selector, by, value } as FlowStep;
  }
  return { ...step, selector, by, value } as FlowStep;
}

/** Apply mirror-picked selector to the step with this flowgram node id (shallow selector fields only). */
export function mergeSelectorByFlowgramId(
  steps: FlowStep[],
  fgId: string,
  pick: {
    by: string;
    value: string;
    conditions?: Record<string, unknown>;
    instance?: number;
  }
): FlowStep[] {
  return mergeStepByFlowgramId(steps, fgId, (prev) => {
    if (!SELECTOR_STEP_TYPES.has(prev.type)) return prev;
    return mergeSelectorOntoStep(prev, pick);
  });
}

export function findStepByFlowgramId(
  steps: FlowStep[],
  fgId: string
): FlowStep | null {
  for (const s of steps) {
    const hit = findOneDeep(s, fgId);
    if (hit) return hit;
  }
  return null;
}

function findOneDeep(s: FlowStep, fgId: string): FlowStep | null {
  if ((s as Record<string, unknown>)[FG] === fgId) return s;
  const t = s.type;
  if (hasThenElseBranches(t)) {
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
