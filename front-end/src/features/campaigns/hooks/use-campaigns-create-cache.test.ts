import assert from 'node:assert/strict';
import { test } from 'node:test';
import { QueryClient } from '@tanstack/react-query';
import { syncCreatedCampaignCaches } from '../lib/campaign-create-cache';
import type { CampaignOut } from '../types';
import type { CampaignPage } from '../services/api';

function campaign(id: string, name: string): CampaignOut {
  return {
    id,
    name,
    description: '',
    status: 'DRAFT',
    variables: {},
    per_device_overrides: {},
    scenarios: [],
    created_at: '2026-08-28T00:00:00.000Z',
    updated_at: '2026-08-28T00:00:00.000Z'
  } as unknown as CampaignOut;
}

test('created campaign appears immediately in the first paginated campaign page', () => {
  const qc = new QueryClient();
  const existing = campaign('campaign-old', 'Old campaign');
  const created = campaign('campaign-new', 'Newest campaign');

  qc.setQueryData<CampaignPage>(['campaigns', 'page', '', 1, 10], {
    items: [existing],
    total: 1
  });

  syncCreatedCampaignCaches(qc, created);

  const page = qc.getQueryData<CampaignPage>(['campaigns', 'page', '', 1, 10]);
  assert.equal(page?.total, 2);
  assert.deepEqual(
    page?.items.map((item) => item.id),
    ['campaign-new', 'campaign-old']
  );
});
