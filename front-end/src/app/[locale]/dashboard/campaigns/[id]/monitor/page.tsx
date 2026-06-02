'use client';

import { useParams } from 'next/navigation';
import { CampaignMonitorPageView } from '@/features/campaigns/components/campaign-monitor/campaign-monitor-page';

export default function CampaignMonitorPage() {
  const params = useParams();
  const id = typeof params.id === 'string' ? params.id : '';

  return (
    <div className='p-4 sm:p-6'>
      <CampaignMonitorPageView campaignId={id} />
    </div>
  );
}
