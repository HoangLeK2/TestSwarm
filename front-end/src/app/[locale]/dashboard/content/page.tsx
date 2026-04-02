'use client';

import { useSearchParams } from 'next/navigation';
import { Database } from 'lucide-react';
import { ContentViewer } from '@/features/content/components/content-viewer';

export default function ContentPage() {
  const params = useSearchParams();
  const campaignId = params.get('campaign_id') ?? undefined;

  return (
    <div className='flex flex-col gap-6 p-6'>
      <div className='flex items-center gap-3'>
        <div className='flex size-9 items-center justify-center rounded-lg bg-primary/10'>
          <Database className='size-5 text-primary' />
        </div>
        <div>
          <h1 className='text-xl font-bold leading-tight'>Kết quả thu thập</h1>
          <p className='text-xs text-muted-foreground'>
            Dữ liệu được cào từ tất cả các lần chạy kịch bản
          </p>
        </div>
      </div>

      <ContentViewer defaultCampaignId={campaignId} />
    </div>
  );
}
