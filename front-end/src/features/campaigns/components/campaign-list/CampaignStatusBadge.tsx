'use client';

import { Loader2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import {
  campaignStatusLabel,
  campaignStatusVariant
} from '../../campaign-status-ui';
import { useCampaignStopDrain } from '../../hooks/use-campaign-stop-drain';
import type { CampaignStatus } from '../../types';
import { cn } from '@/lib/utils';

type Props = {
  campaignId: string;
  status: string;
  statusLabels: Record<CampaignStatus, string>;
  className?: string;
};

export function CampaignStatusBadge({
  campaignId,
  status,
  statusLabels,
  className
}: Props) {
  const t = useTranslations('campaignsFeature.list');
  const { isStopping, activeWorkflowCount, activeExecutionCount } =
    useCampaignStopDrain(campaignId, status);

  if (isStopping) {
    const detail =
      activeWorkflowCount + activeExecutionCount > 0
        ? t('stoppingDetail', {
            workflows: activeWorkflowCount,
            executions: activeExecutionCount
          })
        : t('statusStopping');
    return (
      <Badge
        variant='outline'
        className={cn(
          'gap-1 border-amber-500/40 bg-amber-500/10 text-[10px] text-amber-800 dark:text-amber-200',
          className
        )}
        title={detail}
      >
        <Loader2 className='size-3 shrink-0 animate-spin' aria-hidden />
        {t('statusStopping')}
      </Badge>
    );
  }

  return (
    <Badge
      variant={campaignStatusVariant(status)}
      className={cn('text-[10px] font-normal', className)}
    >
      {campaignStatusLabel(status, statusLabels)}
    </Badge>
  );
}
