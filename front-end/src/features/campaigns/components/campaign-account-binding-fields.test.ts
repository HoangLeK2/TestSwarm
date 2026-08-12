import assert from 'node:assert/strict';
import test from 'node:test';
import {
  campaignBindingFromEntity,
  campaignBindingToPayload
} from '../lib/campaign-account-binding';

test('preserves per-device overrides with a group fallback', () => {
  const value = campaignBindingFromEntity({
    account_group_id: 'group-1',
    per_device_accounts: { 'device-1': 'account-1' }
  });

  assert.deepEqual(campaignBindingToPayload(value), {
    account_group_id: 'group-1',
    per_device_accounts: { 'device-1': 'account-1' }
  });
});

test('emits per-device overrides without a fallback', () => {
  assert.deepEqual(
    campaignBindingToPayload({
      mode: 'none',
      accountGroupId: '',
      scenarioAccountId: '',
      perDeviceAccounts: { 'device-1': 'account-1', 'device-2': '' }
    }),
    { per_device_accounts: { 'device-1': 'account-1' } }
  );
});
