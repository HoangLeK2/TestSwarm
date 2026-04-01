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
import { MonitorContent } from './monitor-content';
import type { CampaignOut } from '../../types';

interface Props {
  campaign: CampaignOut;
  children?: React.ReactNode;
}

export function CampaignMonitorDialog({ campaign, children }: Props) {
  const isRunning = campaign.status === 'running';

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
                disabled={!isRunning}
              >
                <Activity size={13} />
              </Button>
            )}
          </DialogTrigger>
        </TooltipTrigger>
        <TooltipContent side='top' className='text-xs'>
          Theo dõi tiến trình
        </TooltipContent>
      </Tooltip>

      <DialogContent className='max-w-2xl p-0 gap-0'>
        <DialogHeader className='border-b px-4 py-3'>
          <div className='flex items-center gap-2'>
            <Activity size={15} className='text-primary' />
            <DialogTitle className='text-sm font-semibold'>
              Theo dõi — {campaign.name}
            </DialogTitle>
            <span className='ml-auto rounded-full bg-green-500/15 px-2 py-0.5 text-[10px] font-bold text-green-600 dark:text-green-400'>
              ĐANG CHẠY
            </span>
          </div>
        </DialogHeader>

        <MonitorContent campaignId={campaign.id} />
      </DialogContent>
    </Dialog>
  );
}
