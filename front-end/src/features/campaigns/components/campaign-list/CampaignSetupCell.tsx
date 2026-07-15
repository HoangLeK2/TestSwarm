'use client';

import type { CampaignOut } from '../../types';
import { CampaignDevicesSummary } from './CampaignDevicesSummary';
import { CampaignScenarioSummary } from './CampaignScenarioSummary';

const TRIGGER =
  'h-7 w-full max-w-[11rem] justify-start gap-1.5 px-2 text-[11px]';

export function CampaignSetupCell({ campaign }: { campaign: CampaignOut }) {
  return (
    <div className='flex min-w-[9.5rem] flex-col gap-1'>
      <CampaignDevicesSummary
        campaignId={campaign.id}
        campaignName={campaign.name}
        targetGroupId={campaign.target_group_id}
        initialDevices={campaign.devices}
        triggerClassName={TRIGGER}
      />
      <CampaignScenarioSummary campaign={campaign} triggerClassName={TRIGGER} />
    </div>
  );
}
