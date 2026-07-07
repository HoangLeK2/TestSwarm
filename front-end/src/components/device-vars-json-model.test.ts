import assert from 'node:assert/strict';
import test from 'node:test';
import { mergeCampaignScenarioVariables } from './device-vars-json-model';

test('campaign variables override selected scenario defaults in device-var preview', () => {
  const merged = mergeCampaignScenarioVariables(
    {
      comment_text: 'campaign-specific',
      kept_from_campaign: 12,
      __USER_ID__: 'hidden'
    },
    {
      comment_text: 'scenario-default',
      scenario_only: { type: 'string', default: 'from scenario' },
      '1invalid_key': 'hidden'
    }
  );

  assert.deepEqual(merged, {
    comment_text: 'campaign-specific',
    kept_from_campaign: 12,
    scenario_only: 'from scenario'
  });
});
