'use client';

import { useSearchParams } from 'next/navigation';
import { CampaignList } from '@/features/campaigns/components/campaign-list';
import { CampaignDeepLink } from '@/features/campaigns/components/campaign-deep-link';
import { useTranslations } from 'next-intl';

export default function CampaignsPage() {
  const t = useTranslations('campaignsFeature.page');
  const searchParams = useSearchParams();
  const attachScenarioId = searchParams.get('attach_scenario');
  const openCreateCampaign = searchParams.get('new') === '1';

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
      <CampaignDeepLink>
        <CampaignList
          attachScenarioId={attachScenarioId}
          openCreateCampaign={openCreateCampaign}
        />
      </CampaignDeepLink>
    </div>
  );
}
