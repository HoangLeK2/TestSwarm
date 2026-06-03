'use client';

import { cn } from '@/lib/utils';
import type { CampaignOut } from '../../types';
import {
  campaignRowAnchorId,
  campaignRowHighlightClass
} from '../../lib/campaign-row-anchor';
import { CampaignMobileCard } from './CampaignMobileCard';

export function CampaignMobileList({
  campaigns,
  statusLabel,
  highlightCampaignId = null,
  withRowAnchor = true
}: {
  campaigns: CampaignOut[];
  statusLabel: Record<string, string>;
  highlightCampaignId?: string | null;
  withRowAnchor?: boolean;
}) {
  return (
    <div className='flex flex-col gap-3 lg:hidden'>
      {campaigns.map((campaign) => (
        <CampaignMobileCard
          key={campaign.id}
          campaign={campaign}
          statusLabel={statusLabel}
          id={withRowAnchor ? campaignRowAnchorId(campaign.id) : undefined}
          className={cn(
            highlightCampaignId === campaign.id && campaignRowHighlightClass
          )}
        />
      ))}
    </div>
  );
}
