'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { RefreshCw } from 'lucide-react';
import { useTranslations } from 'next-intl';
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
import { Progress } from '@/components/ui/progress';
import { toast } from 'sonner';
import type { DeviceOut } from '../../services/manage-api';
import { deviceControlApi } from '../../services/manage-api';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';

type Cmd = 'bootstrap' | 'restart_u2' | 'restart_scrcpy';

const CMD_I18N_KEY: Record<Cmd, 'setup' | 'restartControl' | 'restartStream'> =
  {
    bootstrap: 'setup',
    restart_u2: 'restartControl',
    restart_scrcpy: 'restartStream'
  };

const CMD_TIMEOUT: Record<Cmd, number> = {
  bootstrap: 60,
  restart_u2: 30,
  restart_scrcpy: 20
};

function RunningState({
  label,
  timeout,
  elapsed
}: {
  label: string;
  timeout: number;
  elapsed: number;
}) {
  const t = useTranslations('devicesList.commands');
  const pct = Math.min(100, Math.round((elapsed / timeout) * 100));

  return (
    <div className='space-y-3 py-2'>
      <div className='flex items-center gap-2 text-sm text-muted-foreground'>
        <RefreshCw size={14} className='animate-spin' />
        <span>{t('running', { label, elapsed, timeout })}</span>
      </div>
      <Progress value={pct} className='h-2' />
    </div>
  );
}

export function DeviceCmdButton({
  device,
  cmd,
  trigger
}: {
  device: DeviceOut;
  cmd: Cmd;
  trigger?: ReactNode;
}) {
  const t = useTranslations('devicesList.commands');
  const i18nKey = CMD_I18N_KEY[cmd];
  const label = t(`${i18nKey}.label`);
  const description = t(`${i18nKey}.description`);
  const timeout = CMD_TIMEOUT[cmd];
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!running) {
      setElapsed(0);
      return;
    }
    const start = Date.now();
    const iv = setInterval(
      () => setElapsed(Math.floor((Date.now() - start) / 1000)),
      500
    );
    return () => clearInterval(iv);
  }, [running]);

  const handleRun = async () => {
    setRunning(true);
    const toastId = toast.loading(t('toastRunning', { label }));
    try {
      const fnMap: Record<Cmd, (id: string) => Promise<any>> = {
        bootstrap: deviceControlApi.bootstrap,
        restart_u2: deviceControlApi.restartU2,
        restart_scrcpy: deviceControlApi.restartScrcpy
      };
      const res = await fnMap[cmd](device.id);
      if (res.ok) {
        toast.success(t('toastSuccess', { label }), { id: toastId });
      } else {
        toast.error(t('toastFailed', { label }), {
          id: toastId,
          description: res.output || res.error
        });
      }
    } catch (e: any) {
      toast.error(t('toastError', { label }), {
        id: toastId,
        description: e?.message
      });
    } finally {
      setRunning(false);
      setOpen(false);
    }
  };

  const defaultTrigger = (
    <Button
      size='sm'
      variant='outline'
      className='h-8 px-2.5 text-[11px]'
      disabled={running}
      aria-label={label}
    >
      {label}
    </Button>
  );

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      {trigger ? (
        <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      ) : (
        <Tooltip delayDuration={400}>
          <TooltipTrigger asChild>
            <AlertDialogTrigger asChild>{defaultTrigger}</AlertDialogTrigger>
          </TooltipTrigger>
          <TooltipContent
            side='bottom'
            className='max-w-[min(100vw-2rem,22rem)] text-xs leading-relaxed'
          >
            <div className='font-medium'>{label}</div>
            <div className='mt-0.5 text-muted-foreground'>{description}</div>
          </TooltipContent>
        </Tooltip>
      )}
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {label} — {device.name || device.serial}
          </AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>

        {running && (
          <RunningState label={label} timeout={timeout} elapsed={elapsed} />
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={running}>
            {t('cancel')}
          </AlertDialogCancel>
          {!running && (
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                handleRun();
              }}
            >
              {t('run')}
            </AlertDialogAction>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
