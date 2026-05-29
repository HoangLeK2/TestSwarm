'use client';
import { CampaignList } from '@/features/campaigns/components/campaign-list';
import { useTranslations } from 'next-intl';

export default function CampaignsPage() {
  const t = useTranslations('campaignsFeature.page');
  return (
    <div className='space-y-4'>
      <div className='flex items-start justify-between gap-4'>
        <div className='space-y-1'>
          <h1 className='text-xl font-bold tracking-tight text-foreground'>
            {t('title')}
          </h1>
          <p className='text-sm text-muted-foreground'>{t('subtitle')}</p>
        </div>
      </div>
      <CampaignList />
    </div>
  );
}
