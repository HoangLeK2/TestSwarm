'use client';
import { CampaignList } from '@/features/campaigns/components/campaign-list';

export default function CampaignsPage() {
  return (
    <div >
      <div className=''>
        <div className='mb-4 flex items-center justify-between'>
          <div>
            <h1 className='text-xl font-bold tracking-tight text-foreground'>Campaigns</h1>
            <p className='text-sm text-muted-foreground'>
              Tạo và chạy kịch bản tự động trên nhiều thiết bị
            </p>
          </div>
        </div>
        <CampaignList />
      </div>
    </div>
  );
}
