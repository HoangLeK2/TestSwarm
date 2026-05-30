'use client';

import { useSearchParams } from 'next/navigation';
import { ContentViewer } from '@/features/content/components/content-viewer';

export default function ContentPage() {
  const params = useSearchParams();
  const campaignId = params.get('campaign_id') ?? undefined;
  const executionId = params.get('execution_id') ?? undefined;

  return (
    <div className=''>
      <ContentViewer
        defaultCampaignId={campaignId}
        defaultExecutionId={executionId}
      />
    </div>
  );
}
