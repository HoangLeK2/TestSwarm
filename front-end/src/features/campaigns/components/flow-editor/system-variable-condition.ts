import type { FlowStep } from '../scenario-steps/types';

export const PLATFORM_SESSION_READY_VARIABLE = 'FACEBOOK_SESSION_READY';

export function normalizeSystemVariableCondition(step: FlowStep): FlowStep {
  if (
    step.type !== 'if_variable' ||
    step.name !== PLATFORM_SESSION_READY_VARIABLE
  ) {
    return step;
  }

  const next = { ...step } as FlowStep;
  delete next.not_equals;
  delete next.contains;
  delete next.greater_than;
  next.equals = step.equals ?? true;
  return next;
}
