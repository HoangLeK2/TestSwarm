import type { QueryClient } from '@tanstack/react-query';

import { normalizeCampaignOut } from '@/features/campaigns/services/api';
import type { CampaignOut } from '@/features/campaigns/types';

export function syncCampaignDetailCaches(
  queryClient: QueryClient,
  campaignId: string,
  rawCampaign: unknown
) {
  const campaign = normalizeCampaignOut(
    rawCampaign as CampaignOut | Record<string, unknown> | null | undefined
  );
  if (!campaign) return;

  queryClient.setQueryData(
    ['campaign', campaignId, 'global-vars-preview'],
    campaign
  );
  queryClient.setQueryData(['campaigns', campaignId], campaign);
  queryClient.setQueryData<CampaignOut[]>(['campaigns'], (old) =>
    old?.map((row) => (row.id === campaignId ? { ...row, ...campaign } : row))
  );
  void queryClient.invalidateQueries({
    queryKey: ['campaigns', campaignId],
    exact: true
  });
  void queryClient.invalidateQueries({ queryKey: ['campaigns'], exact: true });
}
