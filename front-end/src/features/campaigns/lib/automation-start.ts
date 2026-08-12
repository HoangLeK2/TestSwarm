export type CampaignRunJourney = 'automation' | 'dispatch' | 'run';
export type AutomationRunState =
  | 'inactive'
  | 'starting'
  | 'running'
  | 'pausing'
  | 'paused'
  | 'cancelling'
  | 'completed'
  | 'cancelled'
  | 'failed';
export type AutomationPrimaryAction =
  | 'setup'
  | 'monitor'
  | 'resume'
  | 'inspect';

export function campaignRunJourney(
  isEntityCampaign: boolean,
  isContinuous: boolean
): CampaignRunJourney {
  if (!isEntityCampaign) return 'run';
  return isContinuous ? 'automation' : 'dispatch';
}

export function automationRunState(variables: unknown): AutomationRunState {
  if (!variables || typeof variables !== 'object') return 'inactive';
  const metadata = (variables as Record<string, unknown>)._continuous_crawl;
  if (!metadata || typeof metadata !== 'object') return 'inactive';
  const status = String(
    (metadata as Record<string, unknown>).status || 'inactive'
  );
  const states: AutomationRunState[] = [
    'starting',
    'running',
    'pausing',
    'paused',
    'cancelling',
    'completed',
    'cancelled',
    'failed'
  ];
  return states.includes(status as AutomationRunState)
    ? (status as AutomationRunState)
    : 'inactive';
}

export function automationPrimaryAction(
  state: AutomationRunState
): AutomationPrimaryAction {
  if (['starting', 'running', 'pausing', 'cancelling'].includes(state))
    return 'monitor';
  if (state === 'paused') return 'resume';
  if (state === 'failed') return 'inspect';
  return 'setup';
}

export function isAlreadyActiveError(error: unknown): boolean {
  const detail = (error as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail;
  return Boolean(
    detail &&
      typeof detail === 'object' &&
      !Array.isArray(detail) &&
      (detail as { code?: unknown }).code === 'CONTINUOUS_CRAWL_ALREADY_ACTIVE'
  );
}

export type ReadinessAction =
  | 'devices'
  | 'targets'
  | 'source'
  | 'account'
  | 'retry';

export type ReadinessProblem = {
  code: string;
  action: ReadinessAction;
};

export function shouldResumeAutomationReview(
  repairDialogOpen: boolean,
  resumeRequested: boolean
): boolean {
  return !repairDialogOpen && resumeRequested;
}

export function readinessProblemFromError(error: unknown): ReadinessProblem {
  const response = (
    error as {
      response?: { data?: { detail?: unknown; code?: unknown } };
    }
  )?.response;
  const detail = response?.data?.detail;
  const detailCode =
    detail && typeof detail === 'object' && !Array.isArray(detail)
      ? (detail as { code?: unknown }).code
      : undefined;
  const code = String(detailCode || response?.data?.code || 'UNKNOWN');

  if (
    ['EMPTY_DISPATCH_TARGET', 'DEVICE_NOT_FOUND', 'DEVICE_OFFLINE'].includes(
      code
    )
  ) {
    return { code, action: 'devices' };
  }
  if (['SOURCE_POOL_REQUIRED', 'ENTITY_POOL_EXHAUSTED'].includes(code)) {
    return { code, action: 'source' };
  }
  if (code === 'DEVICE_TARGETS_REQUIRED') {
    return { code, action: 'targets' };
  }
  if (
    ['ACCOUNT_NOT_BOUND', 'ACCOUNT_NOT_FOUND', 'ACCOUNT_UNAVAILABLE'].includes(
      code
    )
  ) {
    return { code, action: 'account' };
  }
  return { code, action: 'retry' };
}
