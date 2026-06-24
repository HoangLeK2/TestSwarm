'use client';

import { MonitorPlay } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { useTranslations } from 'next-intl';
import { MonitorContent } from './monitor-content';
import { MonitorControlBar } from './monitor-control-bar';
import { Z_CAMPAIGN_MONITOR } from '@/lib/z-index';
import type { CampaignOut } from '../../types';
import { isCampaignActiveExecution } from '../../types';

interface Props {
  campaign: CampaignOut;
  children?: React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function CampaignMonitorDialog({
  campaign,
  children,
  open,
  onOpenChange
}: Props) {
  const t = useTranslations('campaignsFeature.list');
  const isRunning = isCampaignActiveExecution(campaign.status);
  const statusLabel = isRunning
    ? t('monitorStatusRunning')
    : t('monitorStatusIdle');
  const statusClass = isRunning
    ? 'bg-green-500/15 text-green-600 dark:text-green-400'
    : 'bg-blue-500/15 text-blue-600 dark:text-blue-400';

  const controlled = open !== undefined;
  const trigger = children ?? (
    <Button
      size='sm'
      variant='secondary'
      className='h-7 gap-1.5 border px-2 text-xs shadow-sm'
    >
      <MonitorPlay size={13} className='shrink-0' />
      <span className='max-w-[7rem] truncate'>{t('titleMonitor')}</span>
    </Button>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {!controlled ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <DialogTrigger asChild>{trigger}</DialogTrigger>
          </TooltipTrigger>
          <TooltipContent
            side='top'
            className='max-w-xs text-left text-xs leading-snug'
          >
            {t('monitorTooltip')}
          </TooltipContent>
        </Tooltip>
      ) : null}

      <DialogContent
        zIndex={Z_CAMPAIGN_MONITOR}
        className='flex max-h-[min(95dvh,1200px)] min-h-[min(72dvh,820px)] w-[min(99vw,1600px)] min-w-0 max-w-[min(99vw,1600px)] flex-col gap-0 overflow-hidden p-0 sm:!max-w-[min(99vw,1600px)] sm:rounded-xl'
      >
        <DialogHeader className='shrink-0 border-b px-6 py-4 pr-14'>
          <div className='flex min-w-0 items-center gap-3'>
            <MonitorPlay size={20} className='shrink-0 text-primary' />
            <DialogTitle className='min-w-0 flex-1 text-base font-semibold leading-snug sm:text-lg'>
              {t('monitorTitle', { campaign: campaign.name })}
            </DialogTitle>
            <span
              className={`shrink-0 rounded-full px-3 py-1 text-xs font-bold ${statusClass}`}
            >
              {statusLabel}
            </span>
          </div>
        </DialogHeader>

        <MonitorControlBar campaign={campaign} />

        <div className='min-h-0 flex-1 overflow-y-auto overflow-x-hidden'>
          <MonitorContent campaignId={campaign.id} isRunning={isRunning} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
