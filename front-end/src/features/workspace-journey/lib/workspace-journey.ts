export type WorkspaceJourneyStepKey =
  | 'devices'
  | 'accounts'
  | 'scenarios'
  | 'campaigns'
  | 'automation';

export type WorkspaceJourneyStepState = 'complete' | 'current' | 'upcoming';

export type WorkspaceJourneySignals = {
  deviceCount: number;
  linkedAccountCount: number;
  runnableScenarioCount: number;
  readyCampaignCount: number;
  campaignRunCount: number;
  activeScheduleCount: number;
};

export type WorkspaceJourneyStep = {
  key: WorkspaceJourneyStepKey;
  state: WorkspaceJourneyStepState;
};

const STEP_KEYS: WorkspaceJourneyStepKey[] = [
  'devices',
  'accounts',
  'scenarios',
  'campaigns',
  'automation'
];

/**
 * Readiness is intentionally sequential. Existing seed data later in the
 * journey must not make a workspace look ready while an earlier prerequisite
 * is still missing.
 */
export function buildWorkspaceJourney(
  signals: WorkspaceJourneySignals
): WorkspaceJourneyStep[] {
  const ready = [
    signals.deviceCount > 0,
    signals.linkedAccountCount > 0,
    signals.runnableScenarioCount > 0,
    signals.readyCampaignCount > 0,
    signals.campaignRunCount > 0 && signals.activeScheduleCount > 0
  ];

  let prerequisitesReady = true;
  let currentAssigned = false;

  return STEP_KEYS.map((key, index) => {
    const complete = prerequisitesReady && ready[index];
    prerequisitesReady = complete;

    if (complete) return { key, state: 'complete' };
    if (!currentAssigned) {
      currentAssigned = true;
      return { key, state: 'current' };
    }
    return { key, state: 'upcoming' };
  });
}

export function completedWorkspaceJourneySteps(
  steps: WorkspaceJourneyStep[]
): number {
  return steps.filter((step) => step.state === 'complete').length;
}
