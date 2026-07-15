import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  explicitCampaignDeviceAssignmentsKnown,
  resolveExplicitCampaignDevices,
  shouldFetchExplicitCampaignDevices
} from './campaign-device-summary-state.ts';

describe('campaign-device-summary-state', () => {
  it('fetches immediately when campaign rows do not embed device assignments', () => {
    assert.equal(
      shouldFetchExplicitCampaignDevices(undefined, false, false),
      true
    );
  });

  it('keeps closed rows lazy when embedded device assignments are already known', () => {
    assert.equal(shouldFetchExplicitCampaignDevices([], false, false), false);
    assert.equal(
      shouldFetchExplicitCampaignDevices([{ id: 'd1' }], false, false),
      false
    );
  });

  it('fetches known embedded rows when the popover or add dialog opens', () => {
    assert.equal(shouldFetchExplicitCampaignDevices([], true, false), true);
    assert.equal(shouldFetchExplicitCampaignDevices([], false, true), true);
  });

  it('prefers fetched devices over embedded row devices', () => {
    assert.deepEqual(
      resolveExplicitCampaignDevices([{ id: 'fresh' }], [{ id: 'stale' }]),
      [{ id: 'fresh' }]
    );
  });

  it('tracks whether assignments are known before rendering empty state', () => {
    assert.equal(
      explicitCampaignDeviceAssignmentsKnown(undefined, undefined),
      false
    );
    assert.equal(explicitCampaignDeviceAssignmentsKnown([], undefined), true);
    assert.equal(explicitCampaignDeviceAssignmentsKnown(undefined, []), true);
  });
});
