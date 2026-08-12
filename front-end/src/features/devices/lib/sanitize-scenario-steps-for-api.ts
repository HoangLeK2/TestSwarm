import { applyStepRetrySanitize } from '../../campaigns/components/flow-editor/step-retry-policy';
import { normalizeSelectorStepFields } from './scenario-selector-step';

type SelectorBy =
  | 'resource-id'
  | 'text'
  | 'xpath'
  | 'class name'
  | 'description'
  | 'descriptionContains'
  | 'descriptionStartsWith';

const ALLOWED_SELECTOR_BY: readonly SelectorBy[] = [
  'resource-id',
  'text',
  'xpath',
  'class name',
  'description',
  'descriptionContains',
  'descriptionStartsWith'
];

function normalizeSelectorBy(
  by: unknown,
  fallback: SelectorBy = 'text'
): SelectorBy {
  const raw = String(by ?? '').trim();
  if (!raw) return fallback;
  if (ALLOWED_SELECTOR_BY.includes(raw as SelectorBy)) return raw as SelectorBy;
  const lower = raw.toLowerCase().replace(/\s+/g, '');
  if (
    lower === 'content-desc' ||
    lower === 'contentdesc' ||
    lower === 'description' ||
    lower === 'accessibilityid'
  )
    return 'description';
  if (lower === 'content-desccontains' || lower === 'descriptioncontains')
    return 'descriptionContains';
  if (lower === 'content-descstartswith' || lower === 'descriptionstartswith')
    return 'descriptionStartsWith';
  if (lower === 'classname' || lower === 'class-name') return 'class name';
  return fallback;
}

export function sanitizeScenarioStep(step: any): any {
  if (!step || typeof step !== 'object') return step;
  const next: any = { ...step };
  delete next._id;
  delete next._fgId;
  if (next.by != null) next.by = normalizeSelectorBy(next.by);
  if (next.type === 'repeat') {
    const c = Number(next.count);
    if (!Number.isFinite(c) || c < 1) next.count = 3;
  }
  if (next.selector && typeof next.selector === 'object') {
    next.selector = {
      ...next.selector,
      ...(next.selector.by != null
        ? { by: normalizeSelectorBy(next.selector.by) }
        : {})
    };
  }
  if (next.condition && typeof next.condition === 'object') {
    const cond = { ...(next.condition as Record<string, any>) };
    if (
      cond.element_exists &&
      typeof cond.element_exists === 'object' &&
      cond.element_exists.by != null
    ) {
      cond.element_exists = {
        ...cond.element_exists,
        by: normalizeSelectorBy(cond.element_exists.by)
      };
    }
    if (
      cond.element_not_exists &&
      typeof cond.element_not_exists === 'object' &&
      cond.element_not_exists.by != null
    ) {
      cond.element_not_exists = {
        ...cond.element_not_exists,
        by: normalizeSelectorBy(cond.element_not_exists.by)
      };
    }
    next.condition = cond;
  }
  if (Array.isArray(next.then)) next.then = next.then.map(sanitizeScenarioStep);
  if (Array.isArray(next.else)) next.else = next.else.map(sanitizeScenarioStep);
  if (Array.isArray(next.steps))
    next.steps = next.steps.map(sanitizeScenarioStep);
  if (Array.isArray(next.branches)) {
    next.branches = next.branches.map((br: any) =>
      br && typeof br === 'object'
        ? {
            ...br,
            ...(Array.isArray(br.steps)
              ? { steps: br.steps.map(sanitizeScenarioStep) }
              : {})
          }
        : br
    );
  }
  applyStepRetrySanitize(next);
  return normalizeSelectorStepFields(next);
}

export function sanitizeScenarioStepsForApi(input: unknown): any[] {
  if (!Array.isArray(input)) return [];
  return input.map(sanitizeScenarioStep);
}
