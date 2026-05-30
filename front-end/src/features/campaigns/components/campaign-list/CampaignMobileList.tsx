'use client';

import type { CampaignOut, CampaignStatus } from '../../types';
import { CampaignMobileCard } from './CampaignMobileCard';

export function CampaignMobileList({
  campaigns,
  statusLabel,
  statusVariant
}: {
  campaigns: CampaignOut[];
  statusLabel: Record<CampaignStatus, string>;
  statusVariant: Record<
    CampaignStatus,
    'secondary' | 'default' | 'outline' | 'destructive'
  >;
}) {
  return (
    <div className='flex flex-col gap-3 lg:hidden'>
      {campaigns.map((campaign) => (
        <CampaignMobileCard
          key={campaign.id}
          campaign={campaign}
          statusLabel={statusLabel}
          statusVariant={statusVariant}
        />
      ))}
    </div>
  );
}
