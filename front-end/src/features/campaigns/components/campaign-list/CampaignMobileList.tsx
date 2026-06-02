'use client';

import type { CampaignOut } from '../../types';
import { CampaignMobileCard } from './CampaignMobileCard';

export function CampaignMobileList({
  campaigns,
  statusLabel
}: {
  campaigns: CampaignOut[];
  statusLabel: Record<string, string>;
}) {
  return (
    <div className='flex flex-col gap-3 lg:hidden'>
      {campaigns.map((campaign) => (
        <CampaignMobileCard
          key={campaign.id}
          campaign={campaign}
          statusLabel={statusLabel}
        />
      ))}
    </div>
  );
}
