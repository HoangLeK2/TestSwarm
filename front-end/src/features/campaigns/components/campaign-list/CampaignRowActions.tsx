'use client';

import { useCampaignDevices } from '../../hooks/use-campaigns';
import type { CampaignOut } from '../../types';
import { AddDevicesToCampaignDialog } from '../add-devices-dialog';
import { ScenarioListDialog } from '../scenario-list-dialog';
import { CampaignActions } from './CampaignActions';

export function CampaignRowActions({ campaign }: { campaign: CampaignOut }) {
  const { data: devices = [] } = useCampaignDevices(campaign.id);

  return (
    <div className='flex flex-col items-stretch gap-1'>
      <AddDevicesToCampaignDialog campaignId={campaign.id} campaignName={campaign.name} deviceCount={devices.length} />
      <ScenarioListDialog campaign={campaign} />
      <div className='flex justify-center'>
        <CampaignActions campaign={campaign} />
      </div>
    </div>
  );
}

