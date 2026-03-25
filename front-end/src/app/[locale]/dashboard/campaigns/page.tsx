'use client';
import { CampaignList } from '@/features/campaigns/components/campaign-list';

export default function CampaignsPage() {
  return (
    <div className='min-h-screen bg-gradient-to-b from-background to-muted/20'>
      <div className='container max-w-6xl py-8 px-4'>
        <header className='mb-8'>
          <h1 className='text-2xl font-bold tracking-tight text-foreground'>Campaigns</h1>
          <p className='mt-1 text-sm text-muted-foreground'>
            Tạo và chạy kịch bản tự động trên nhiều thiết bị
          </p>
        </header>
        <CampaignList />
      </div>
    </div>
  );
}
