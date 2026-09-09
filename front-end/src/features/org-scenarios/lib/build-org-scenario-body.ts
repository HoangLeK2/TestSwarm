import { sanitizeScenarioStepsForApi } from '@/features/devices/lib/sanitize-scenario-steps-for-api';
import { normalizeScenarioVariables } from '@/lib/scenario-variables';
import { stripUndeclaredVariableReferencesFromTags } from '@/lib/scenario-variable-references';
import type { OrgScenarioBodyIn } from '../services/api';

function slugifyStepId(raw: string): string {
  const cleaned = raw
    .trim()
    .replace(/^step-/, 's-')
    .replace(/[^a-zA-Z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return cleaned.slice(0, 64) || 'step';
}

function ensureOrgStepIds(step: any, fallbackId: string): any {
  if (!step || typeof step !== 'object') return step;
  const existingId =
    typeof step.id === 'string' && step.id.trim()
      ? step.id.trim()
      : typeof step._id === 'string' && step._id.trim()
        ? slugifyStepId(step._id)
        : '';
  const id = existingId || slugifyStepId(fallbackId);
  const next: Record<string, unknown> = { ...step, id };
  delete next._id;
  delete next._fgId;

  if (Array.isArray(next.then)) {
    next.then = next.then.map((child: unknown, index: number) =>
      ensureOrgStepIds(child, `${id}-then-${index + 1}`)
    );
  }
  if (Array.isArray(next.else)) {
    next.else = next.else.map((child: unknown, index: number) =>
      ensureOrgStepIds(child, `${id}-else-${index + 1}`)
    );
  }
  if (Array.isArray(next.steps)) {
    next.steps = next.steps.map((child: unknown, index: number) =>
      ensureOrgStepIds(child, `${id}-steps-${index + 1}`)
    );
  }
  if (Array.isArray(next.branches)) {
    next.branches = next.branches.map((branch: unknown, bIndex: number) => {
      if (!branch || typeof branch !== 'object') return branch;
      const br = branch as Record<string, unknown>;
      if (!Array.isArray(br.steps)) return br;
      return {
        ...br,
        steps: br.steps.map((child: unknown, index: number) =>
          ensureOrgStepIds(child, `${id}-branch-${bIndex + 1}-${index + 1}`)
        )
      };
    });
  }
  return next;
}

/** Convert control-record steps into an org-scenario body payload accepted by POST /scenarios/{id}/body. */
export function buildOrgScenarioBodyPayload(
  steps: unknown[],
  variables?: Record<string, unknown> | null,
  requirements?: Record<string, unknown> | null
): OrgScenarioBodyIn {
  const sanitized = sanitizeScenarioStepsForApi(steps);
  const withIds = sanitized.map((step, index) =>
    ensureOrgStepIds(step, `step-${index + 1}`)
  );
  const normalizedVariables = normalizeScenarioVariables(variables ?? {});
  return {
    steps: stripUndeclaredVariableReferencesFromTags(
      withIds,
      normalizedVariables
    ),
    variables: normalizedVariables,
    requirements: requirements ?? {}
  };
}
