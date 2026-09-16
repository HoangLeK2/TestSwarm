import type { OrgScenarioSummaryOut } from '../services/api';

/** Org scenario UI is sequence-only (graph / flow editor disabled temporarily). */
export const ORG_SCENARIOS_SEQUENCE_ONLY = true;

/** @deprecated use ORG_SCENARIOS_SEQUENCE_ONLY */
export const CAMPAIGN_SCENARIOS_SEQUENCE_ONLY = ORG_SCENARIOS_SEQUENCE_ONLY;

export function isGraphOrgScenario(
  scenario: { kind?: string | null } | null | undefined
): boolean {
  return (scenario?.kind ?? '').toLowerCase() === 'graph';
}

export function isOrgScenarioAllowedInUi(
  scenario: Pick<OrgScenarioSummaryOut, 'kind'>
): boolean {
  if (ORG_SCENARIOS_SEQUENCE_ONLY && isGraphOrgScenario(scenario)) {
    return false;
  }
  return true;
}

export function isOrgScenarioVisibleInLibrary(
  scenario: Pick<OrgScenarioSummaryOut, 'kind'>
): boolean {
  return isOrgScenarioAllowedInUi(scenario);
}

export function isOrgScenarioVisibleInCampaignPicker(
  scenario: Pick<OrgScenarioSummaryOut, 'kind' | 'status'>
): boolean {
  if (scenario.status === 'archived') return false;
  return isOrgScenarioAllowedInUi(scenario);
}

export function canSelectOrgScenarioForCampaign(
  scenario: Pick<OrgScenarioSummaryOut, 'kind' | 'status'>
): boolean {
  return isOrgScenarioVisibleInCampaignPicker(scenario);
}
