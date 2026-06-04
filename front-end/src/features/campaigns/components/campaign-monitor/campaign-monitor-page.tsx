'use client';

import { ArrowLeft, Loader2, MonitorPlay } from 'lucide-react';
import Link from 'next/link';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { ROUTES } from '@/config/routes';
import { useCampaign } from '../../hooks/use-campaigns';
import { isCampaignActiveExecution } from '../../types';
import { MonitorControlBar } from './monitor-control-bar';
import { MonitorContent } from './monitor-content';

type Props = {
  campaignId: string;
};

export function CampaignMonitorPageView({ campaignId }: Props) {
  const t = useTranslations('campaignsFeature.list');
  const { data: campaign, isLoading, error } = useCampaign(campaignId);

  if (isLoading) {
    return (
      <div className='flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground'>
        <Loader2 size={16} className='animate-spin' />
        {t('loading')}
      </div>
    );
  }

  if (error || !campaign) {
    return (
      <div className='space-y-4 py-8'>
        <p className='text-sm text-destructive'>{t('loadError')}</p>
        <Button asChild variant='outline' size='sm'>
          <Link href={ROUTES.CAMPAIGNS.ROOT}>
            <ArrowLeft size={14} className='mr-1' />
            {t('monitorPageBack')}
          </Link>
        </Button>
      </div>
    );
  }

  const isRunning = isCampaignActiveExecution(campaign.status);
  const statusLabel = isRunning
    ? t('monitorStatusRunning')
    : t('monitorStatusIdle');
  const statusClass = isRunning
    ? 'bg-green-500/15 text-green-600 dark:text-green-400'
    : 'bg-blue-500/15 text-blue-600 dark:text-blue-400';

  return (
    <div className='space-y-0 overflow-hidden rounded-xl border bg-card shadow-sm'>
      <div className='flex flex-wrap items-center gap-3 border-b px-4 py-4 sm:px-6'>
        <Button asChild variant='ghost' size='sm' className='h-8 gap-1 px-2'>
          <Link href={ROUTES.CAMPAIGNS.DETAIL(campaign.id)}>
            <ArrowLeft size={14} />
            {t('monitorPageBack')}
          </Link>
        </Button>
        <MonitorPlay size={20} className='shrink-0 text-primary' />
        <div className='min-w-0 flex-1'>
          <h1 className='truncate text-base font-semibold sm:text-lg'>
            {t('monitorTitle', { campaign: campaign.name })}
          </h1>
        </div>
        <span
          className={`shrink-0 rounded-full px-3 py-1 text-xs font-bold ${statusClass}`}
        >
          {statusLabel}
        </span>
      </div>

      <MonitorControlBar campaign={campaign} />
      <MonitorContent campaignId={campaign.id} isRunning={isRunning} />
    </div>
  );
}
