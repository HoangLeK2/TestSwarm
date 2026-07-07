import { resolveLatestStepForInlineRun } from '@/features/campaigns/components/flow-editor/inline-run-key';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';

import { sanitizeScenarioStep } from './sanitize-scenario-steps-for-api';

export function prepareInlinePreviewStep(
  steps: FlowStep[],
  runKey: string,
  clickSnapshot: FlowStep
): Record<string, any> {
  const step = resolveLatestStepForInlineRun(steps, runKey, clickSnapshot);
  return sanitizeScenarioStep(
    JSON.parse(JSON.stringify(step)) as FlowStep
  ) as Record<string, any>;
}

export function preparePreviewStepPayload(step: FlowStep): Record<string, any> {
  const payload = sanitizeScenarioStep(
    JSON.parse(JSON.stringify(step)) as FlowStep
  ) as Record<string, any>;
  delete payload._fgId;
  return payload;
}
