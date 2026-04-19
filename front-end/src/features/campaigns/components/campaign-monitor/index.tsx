'use client';

import { MonitorPlay } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useTranslations } from 'next-intl';
import { MonitorContent } from './monitor-content';
import type { CampaignOut } from '../../types';
import { isCampaignActiveExecution } from '../../types';

interface Props {
  campaign: CampaignOut;
  children?: React.ReactNode;
}

export function CampaignMonitorDialog({ campaign, children }: Props) {
  const t = useTranslations('campaignsFeature.list');
  const isRunning = isCampaignActiveExecution(campaign.status);
  const statusLabel = isRunning ? t('monitorStatusRunning') : t('monitorStatusIdle');
  const statusClass = isRunning
    ? 'bg-green-500/15 text-green-600 dark:text-green-400'
    : 'bg-blue-500/15 text-blue-600 dark:text-blue-400';

  return (
    <Dialog>
      <Tooltip>
        <TooltipTrigger asChild>
          <DialogTrigger asChild>
            {children ?? (
              <Button
                size='sm'
                variant='secondary'
                className='h-7 gap-1.5 border px-2 text-xs shadow-sm'
              >
                <MonitorPlay size={13} className='shrink-0' />
                <span className='max-w-[7rem] truncate'>{t('titleMonitor')}</span>
              </Button>
            )}
          </DialogTrigger>
        </TooltipTrigger>
        <TooltipContent side='top' className='max-w-xs text-left text-xs leading-snug'>
          {t('monitorTooltip')}
        </TooltipContent>
      </Tooltip>

      <DialogContent className='flex max-h-[min(85vh,720px)] max-w-2xl flex-col gap-0 overflow-hidden p-0'>
        <DialogHeader className='shrink-0 border-b px-4 py-3 pr-14'>
          <div className='flex min-w-0 items-center gap-2'>
            <MonitorPlay size={15} className='shrink-0 text-primary' />
            <DialogTitle className='min-w-0 flex-1 text-sm font-semibold'>
              {t('monitorTitle', { campaign: campaign.name })}
            </DialogTitle>
            <span
              className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold ${statusClass}`}
            >
              {statusLabel}
            </span>
          </div>
        </DialogHeader>

        <div className='min-h-0 flex-1 overflow-y-auto overflow-x-hidden'>
          <MonitorContent campaignId={campaign.id} isRunning={isRunning} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
