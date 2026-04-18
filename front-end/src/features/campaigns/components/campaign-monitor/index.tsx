'use client';

import { Activity } from 'lucide-react';
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
                variant='ghost'
                className='h-7 gap-1.5 px-2 text-xs'
              >
                <Activity size={13} />
              </Button>
            )}
          </DialogTrigger>
        </TooltipTrigger>
        <TooltipContent side='top' className='text-xs'>
          {t('monitorTooltip')}
        </TooltipContent>
      </Tooltip>

      <DialogContent className='max-w-2xl p-0 gap-0'>
        <DialogHeader className='border-b px-4 py-3'>
          <div className='flex items-center gap-2'>
            <Activity size={15} className='text-primary' />
            <DialogTitle className='text-sm font-semibold'>
              {t('monitorTitle', { campaign: campaign.name })}
            </DialogTitle>
            <span className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-bold ${statusClass}`}>
              {statusLabel}
            </span>
          </div>
        </DialogHeader>

        <MonitorContent campaignId={campaign.id} isRunning={isRunning} />
      </DialogContent>
    </Dialog>
  );
}
