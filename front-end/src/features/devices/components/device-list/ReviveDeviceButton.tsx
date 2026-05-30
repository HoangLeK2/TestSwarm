'use client';

import { useState } from 'react';
import { HeartPulse } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import { toast } from 'sonner';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import type { DeviceOut } from '../../services/manage-api';
import { deviceControlApi } from '../../services/manage-api';
import { invalidateDeviceFleetQueries } from '../../hooks/use-devices';

export function ReviveDeviceButton({ device }: { device: DeviceOut }) {
  const t = useTranslations('devicesList.revive');
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState(false);

  const label = device.name || device.serial;

  const handleRevive = async () => {
    setRunning(true);
    const toastId = toast.loading(t('toastRunning', { label }));
    try {
      const res = await deviceControlApi.revive(device.id);
      toast.success(t('toastSuccess', { label }), {
        id: toastId,
        description: t('toastSuccessDetail', { state: res.to_state })
      });
      invalidateDeviceFleetQueries(qc);
      setOpen(false);
    } catch (e: unknown) {
      let description: string | undefined;
      if (axios.isAxiosError(e)) {
        const detail = e.response?.data?.detail;
        if (typeof detail === 'string') description = detail;
      } else if (e instanceof Error) {
        description = e.message;
      }
      toast.error(t('toastFailed', { label }), {
        id: toastId,
        description
      });
    } finally {
      setRunning(false);
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <Tooltip delayDuration={400}>
        <TooltipTrigger asChild>
          <AlertDialogTrigger asChild>
            <Button
              size='sm'
              variant='outline'
              className='h-7 border-destructive/40 px-2 text-[11px] text-destructive hover:bg-destructive/10 hover:text-destructive'
              disabled={running}
              aria-label={t('label')}
            >
              <HeartPulse size={12} className='mr-1' />
              {t('label')}
            </Button>
          </AlertDialogTrigger>
        </TooltipTrigger>
        <TooltipContent
          side='bottom'
          className='max-w-[min(100vw-2rem,22rem)] text-xs leading-relaxed'
        >
          <div className='font-medium'>{t('label')}</div>
          <div className='mt-0.5 text-muted-foreground'>{t('description')}</div>
        </TooltipContent>
      </Tooltip>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className='flex items-center gap-2'>
            <HeartPulse size={16} />
            {t('confirmTitle', { label })}
          </AlertDialogTitle>
          <AlertDialogDescription>{t('confirmDescription')}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={running}>{t('cancel')}</AlertDialogCancel>
          <AlertDialogAction
            disabled={running}
            onClick={(e) => {
              e.preventDefault();
              void handleRevive();
            }}
          >
            {running ? t('running') : t('confirmAction')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
