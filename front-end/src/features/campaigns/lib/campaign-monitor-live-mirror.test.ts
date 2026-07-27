import assert from 'node:assert/strict';
import test from 'node:test';

import {
  claimCampaignMonitorLiveMirror,
  getCampaignMonitorLiveMirrorSerial,
  releaseCampaignMonitorLiveMirror,
  subscribeCampaignMonitorLiveMirror
} from './campaign-monitor-live-mirror';

test('campaign monitor live mirror allows only one active serial', () => {
  const seen: Array<string | null> = [];
  const unsubscribe = subscribeCampaignMonitorLiveMirror((serial) => {
    seen.push(serial);
  });

  claimCampaignMonitorLiveMirror('device-a');
  assert.equal(getCampaignMonitorLiveMirrorSerial(), 'device-a');

  claimCampaignMonitorLiveMirror('device-b');
  assert.equal(getCampaignMonitorLiveMirrorSerial(), 'device-b');

  releaseCampaignMonitorLiveMirror('device-a');
  assert.equal(getCampaignMonitorLiveMirrorSerial(), 'device-b');

  releaseCampaignMonitorLiveMirror('device-b');
  assert.equal(getCampaignMonitorLiveMirrorSerial(), null);
  assert.deepEqual(seen, ['device-a', 'device-b', null]);

  unsubscribe();
});
