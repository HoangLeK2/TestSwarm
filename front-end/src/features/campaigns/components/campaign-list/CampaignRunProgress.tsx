'use client';

import { useTranslations } from 'next-intl';
import { Progress } from '@/components/ui/progress';
import { useCampaignProgress } from '../../hooks/use-campaigns';

export function CampaignRunProgress({ campaignId, isRunning }: { campaignId: string; isRunning: boolean }) {
  const t = useTranslations('campaignsFeature.list');
  const { data: progress } = useCampaignProgress(campaignId, isRunning);
  if (!isRunning || !progress || progress.total === 0) return null;

  return (
    <div className='flex flex-col gap-1 pt-0.5'>
      <div className='flex items-center justify-between text-[10px] text-muted-foreground'>
        <span>{t('progressDone', { done: progress.done, total: progress.total })}</span>
        {progress.failed > 0 && <span className='text-destructive'>{t('progressFailed', { count: progress.failed })}</span>}
        <span>{progress.pct}%</span>
      </div>
      <Progress value={progress.pct} className='h-1' />
    </div>
  );
}

