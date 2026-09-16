import assert from 'node:assert/strict';
import test from 'node:test';

import {
  canSelectOrgScenarioForCampaign,
  isOrgScenarioVisibleInCampaignPicker
} from './campaign-scenario-eligibility.ts';

test('campaign picker allows draft sequence scenarios to be selected', () => {
  const draftScenario = {
    kind: 'sequence',
    status: 'active',
    is_runnable: false
  } as const;

  assert.equal(canSelectOrgScenarioForCampaign(draftScenario), true);
});

test('campaign picker still excludes archived and graph scenarios', () => {
  const archivedScenario = {
    kind: 'sequence',
    status: 'archived'
  } as const;
  const graphScenario = {
    kind: 'graph',
    status: 'active',
    is_runnable: true
  } as const;

  assert.equal(isOrgScenarioVisibleInCampaignPicker(archivedScenario), false);
  assert.equal(canSelectOrgScenarioForCampaign(graphScenario), false);
});
