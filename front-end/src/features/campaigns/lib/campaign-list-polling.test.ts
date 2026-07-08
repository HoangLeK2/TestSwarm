import assert from 'node:assert/strict';
import test from 'node:test';
import {
  CAMPAIGN_ROW_ACTIVE_POLL_MS,
  CAMPAIGN_ROW_ACTIVE_STALE_MS,
  CAMPAIGN_ROW_IDLE_STALE_MS,
  campaignRowPollInterval,
  campaignRowStaleTime,
  shouldFetchCampaignRowDetailsOnMount
} from './campaign-list-polling.ts';

test('campaign list rows only poll active campaigns', () => {
  assert.equal(campaignRowPollInterval('running'), CAMPAIGN_ROW_ACTIVE_POLL_MS);
  assert.equal(campaignRowPollInterval('paused'), CAMPAIGN_ROW_ACTIVE_POLL_MS);
  assert.equal(campaignRowPollInterval('idle'), false);
  assert.equal(campaignRowPollInterval('completed'), false);
  assert.equal(campaignRowPollInterval('failed'), false);
  assert.equal(campaignRowPollInterval('draft'), false);
});

test('campaign list rows keep idle cache warm without realtime polling', () => {
  assert.equal(campaignRowStaleTime('running'), CAMPAIGN_ROW_ACTIVE_STALE_MS);
  assert.equal(campaignRowStaleTime('paused'), CAMPAIGN_ROW_ACTIVE_STALE_MS);
  assert.equal(campaignRowStaleTime('idle'), CAMPAIGN_ROW_IDLE_STALE_MS);
  assert.equal(campaignRowStaleTime('completed'), CAMPAIGN_ROW_IDLE_STALE_MS);
});

test('campaign list only fetches row detail queries on mount for active campaigns', () => {
  assert.equal(shouldFetchCampaignRowDetailsOnMount('running'), true);
  assert.equal(shouldFetchCampaignRowDetailsOnMount('paused'), true);
  assert.equal(shouldFetchCampaignRowDetailsOnMount('idle'), false);
  assert.equal(shouldFetchCampaignRowDetailsOnMount('completed'), false);
  assert.equal(shouldFetchCampaignRowDetailsOnMount('failed'), false);
  assert.equal(shouldFetchCampaignRowDetailsOnMount('draft'), false);
});
