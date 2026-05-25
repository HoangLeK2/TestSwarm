/**
 * Helpers to build/normalize scenario steps with canonical nested `selector` objects.
 * Runtime (device_farm) accepts legacy flat `by`/`value` but prefers `selector: { by, value }`.
 */

export type SelectorBy =
  | 'resource-id'
  | 'text'
  | 'xpath'
  | 'class name'
  | 'content-desc'
  | 'description'
  | 'descriptionContains'
  | 'descriptionStartsWith';

export type ScenarioSelectorShape = {
  by: SelectorBy;
  value: string;
  conditions?: Record<string, unknown>;
  instance?: number;
  index?: number;
  chain?: Record<string, unknown>;
};

const SELECTOR_STEP_TYPES = new Set([
  'tap_selector',
  'wait_element',
  'assert_element',
  'input_selector',
  'long_tap_selector',
  'scroll_to',
  'if_element',
]);

export function selectorFromPick(by: string, value: string): ScenarioSelectorShape {
  return { by: by as SelectorBy, value: String(value ?? '').trim() };
}

export function mergeSelectorShape(
  base: ScenarioSelectorShape | undefined,
  by: string,
  value: string,
): ScenarioSelectorShape {
  const trimmed = String(value ?? '').trim();
  if (base && (base.conditions || base.instance != null || base.chain)) {
    return { ...base, by: by as SelectorBy, value: trimmed };
  }
  return selectorFromPick(by, value);
}

/** Build a recorded tap step (keeps `tap` for screen/visual anchoring + nested selector). */
export function buildRecordedTapStep(args: {
  by: string;
  value: string;
  rx: number;
  ry: number;
  screen?: Record<string, unknown>;
  selector?: ScenarioSelectorShape;
}): Record<string, unknown> {
  const { by, value, rx, ry, screen, selector: specIn } = args;
  const selector = specIn ?? selectorFromPick(by, value);
  return {
    type: 'tap',
    selector,
    by: selector.by,
    value: selector.value,
    fallback: { rx, ry },
    timeout: 4,
    ...(screen ? { screen } : {}),
  };
}

/** Build tap_selector (no screen) — used when recording from campaign dialog embed. */
export function buildTapSelectorStep(args: {
  by: string;
  value: string;
  rx?: number;
  ry?: number;
  timeout?: number;
  selector?: ScenarioSelectorShape;
}): Record<string, unknown> {
  const { by, value, rx, ry, timeout = 8, selector: specIn } = args;
  const selector = specIn ?? selectorFromPick(by, value);
  const step: Record<string, unknown> = {
    type: 'tap_selector',
    selector,
    by: selector.by,
    value: selector.value,
    timeout,
  };
  if (rx != null && ry != null) {
    step.fallback = { rx, ry };
    step.fallback_rx = rx;
    step.fallback_ry = ry;
  }
  return step;
}

export function buildSelectorStep(
  type: string,
  by: string,
  value: string,
  extra?: Record<string, unknown>,
  selector?: ScenarioSelectorShape,
): Record<string, unknown> {
  const spec = selector ?? selectorFromPick(by, value);
  return {
    type,
    selector: spec,
    by: spec.by,
    value: spec.value,
    ...extra,
  };
}

/** Hoist flat by/value into nested selector; sync fallback_rx/ry → fallback. */
export function normalizeSelectorStepFields(step: Record<string, unknown>): Record<string, unknown> {
  if (!step || typeof step !== 'object') return step;
  const next = { ...step };
  const t = String(next.type ?? '');

  if (t === 'tap' && next.selector && typeof next.selector === 'object') {
    const sel = next.selector as Record<string, unknown>;
    if (sel.by && sel.value && !next.by) {
      next.by = sel.by;
      next.value = sel.value;
    }
    return next;
  }

  if (!SELECTOR_STEP_TYPES.has(t)) return next;

  const by = String(next.by ?? (next.selector as Record<string, unknown>)?.by ?? '').trim();
  const value = String(next.value ?? (next.selector as Record<string, unknown>)?.value ?? '').trim();

  if (by && value) {
    const existing = (next.selector && typeof next.selector === 'object'
      ? next.selector
      : {}) as Record<string, unknown>;
    next.selector = {
      ...existing,
      by,
      value,
      ...(existing.conditions ? { conditions: existing.conditions } : {}),
      ...(existing.instance != null ? { instance: existing.instance } : {}),
      ...(existing.chain ? { chain: existing.chain } : {}),
    };
    next.by = by;
    next.value = value;
  }

  const rx = next.fallback_rx ?? (next.fallback as Record<string, unknown>)?.rx;
  const ry = next.fallback_ry ?? (next.fallback as Record<string, unknown>)?.ry;
  if (rx != null && ry != null && t === 'tap_selector') {
    next.fallback = { rx: Number(rx), ry: Number(ry) };
    next.fallback_rx = Number(rx);
    next.fallback_ry = Number(ry);
  }

  return next;
}

export function selectorDisplay(step: Record<string, unknown>): { by?: string; value?: string } {
  const sel = step.selector as Record<string, unknown> | undefined;
  return {
    by: String(sel?.by ?? step.by ?? ''),
    value: String(sel?.value ?? step.value ?? ''),
  };
}
