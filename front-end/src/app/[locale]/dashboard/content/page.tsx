'use client';

import { useSearchParams } from 'next/navigation';
import { CollectedDataViewer } from '@/features/content/components/collected-data-viewer';

export default function ContentPage() {
  const params = useSearchParams();
  const campaignId = params.get('campaign_id') ?? undefined;
  const executionId = params.get('execution_id') ?? undefined;
  const contentHash = params.get('content_hash') ?? undefined;

  return (
    <div className=''>
      <CollectedDataViewer
        defaultCampaignId={campaignId}
        defaultExecutionId={executionId}
        defaultContentHash={contentHash}
      />
    </div>
  );
}
