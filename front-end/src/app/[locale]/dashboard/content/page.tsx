'use client';

import { useSearchParams } from 'next/navigation';
import { Database } from 'lucide-react';
import { ContentViewer } from '@/features/content/components/content-viewer';

export default function ContentPage() {
  const params = useSearchParams();
  const campaignId = params.get('campaign_id') ?? undefined;

  return (
    <div className='flex flex-col gap-6 p-6'>
      <div className='flex items-center gap-4'>
        <div className='flex size-11 items-center justify-center rounded-xl bg-gradient-to-br from-primary/15 to-primary/5 ring-1 ring-primary/20'>
          <Database className='size-5 text-primary' />
        </div>
        <div>
          <h1 className='text-2xl font-bold leading-tight tracking-tight'>Kết quả thu thập</h1>
          <p className='mt-0.5 text-sm text-muted-foreground'>
            Dữ liệu được cào từ tất cả các lần chạy kịch bản
          </p>
        </div>
      </div>

      <ContentViewer defaultCampaignId={campaignId} />
    </div>
  );
}
