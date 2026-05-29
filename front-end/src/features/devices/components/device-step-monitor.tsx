'use client';

import { useState } from 'react';
import { Activity, ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle
} from '@/components/ui/sheet';
import { Loader2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useDeviceRunningWorkflows } from '@/features/campaigns/hooks/use-campaigns';
import {
  parseWorkflowId,
  WorkflowStepList
} from '@/features/campaigns/components/workflow-step-list';
import type { WorkflowInfo } from '@/features/campaigns/types';

function WorkflowSection({
  wf,
  defaultOpen
}: {
  wf: WorkflowInfo;
  defaultOpen?: boolean;
}) {
  const t = useTranslations('devicesFarm.stepMonitor');
  const [open, setOpen] = useState(defaultOpen ?? true);
  const { campaignId } = parseWorkflowId(wf.workflow_id);

  const statusColor: Record<string, string> = {
    RUNNING: 'text-blue-500',
    COMPLETED: 'text-green-500',
    FAILED: 'text-destructive',
    PAUSED: 'text-amber-500'
  };

  return (
    <div className='rounded-md border'>
      <button
        type='button'
        className='flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-accent/30'
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span className='flex-1 truncate text-[11px] text-muted-foreground'>
          {t('campaignLabel')}{' '}
          <span className='font-mono font-semibold text-foreground'>
            #{campaignId ? campaignId.slice(0, 8) : wf.workflow_id.slice(0, 12)}
          </span>
        </span>
        <span
          className={cn(
            'text-[10px] font-bold',
            statusColor[wf.status] ?? 'text-muted-foreground'
          )}
        >
          {wf.status}
        </span>
      </button>
      {open && (
        <div className='border-t px-3 py-3'>
          <WorkflowStepList wf={wf} />
        </div>
      )}
    </div>
  );
}

export function DeviceStepsPanel({ serial }: { serial: string }) {
  const t = useTranslations('devicesFarm.stepMonitor');
  const { data, isLoading } = useDeviceRunningWorkflows(serial, true);
  const workflows = data?.workflows ?? [];

  return (
    <div className='flex flex-col gap-2'>
      {isLoading && (
        <div className='flex items-center justify-center py-8 text-xs text-muted-foreground'>
          <Loader2 size={14} className='mr-2 animate-spin' /> {t('loading')}
        </div>
      )}
      {!isLoading && workflows.length === 0 && (
        <p className='py-8 text-center text-xs text-muted-foreground'>
          {t('noWorkflows')}
        </p>
      )}
      {workflows.map((wf, i) => (
        <WorkflowSection key={wf.workflow_id} wf={wf} defaultOpen={i === 0} />
      ))}
    </div>
  );
}

interface DeviceStepMonitorButtonProps {
  serial: string;
  isBusy: boolean;
  onOpen: (serial: string) => void;
}

/** Lightweight trigger — one shared sheet lives on the device farm page. */
export function DeviceStepMonitorButton({
  serial,
  isBusy,
  onOpen
}: DeviceStepMonitorButtonProps) {
  const t = useTranslations('devicesFarm.stepMonitor');

  return (
    <Button
      type='button'
      size='sm'
      variant={isBusy ? 'outline' : 'ghost'}
      className={cn(
        'relative z-10 shrink-0',
        isBusy
          ? 'h-7 gap-1.5 border-blue-400/50 px-2.5 text-[11px] text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950/30'
          : 'h-7 gap-1 px-2 text-[11px] text-muted-foreground'
      )}
      onClick={() => onOpen(serial)}
    >
      <Activity size={12} className={isBusy ? 'animate-pulse' : ''} />
      {isBusy ? t('running') : t('steps')}
    </Button>
  );
}

interface DeviceStepsSheetProps {
  serial: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Single sheet instance for the whole grid (avoids N Radix portals + polling hooks). */
export function DeviceStepsSheet({
  serial,
  open,
  onOpenChange
}: DeviceStepsSheetProps) {
  const t = useTranslations('devicesFarm.stepMonitor');
  const activeSerial = open && serial ? serial : '';
  const { data, isLoading } = useDeviceRunningWorkflows(
    activeSerial,
    open && !!serial
  );
  const workflows = data?.workflows ?? [];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side='right'
        className='flex w-full flex-col gap-0 p-0 sm:max-w-md'
      >
        <SheetHeader className='border-b px-4 py-3 text-left'>
          <SheetTitle className='flex items-center gap-2 text-sm font-semibold'>
            <Activity size={14} className='text-primary' />
            {t('title')}
          </SheetTitle>
          {serial ? (
            <p className='font-mono text-[10px] text-muted-foreground'>
              {serial}
            </p>
          ) : null}
        </SheetHeader>

        <div className='min-h-0 flex-1 space-y-3 overflow-y-auto p-4'>
          {!serial ? null : isLoading ? (
            <div className='flex items-center justify-center py-8 text-xs text-muted-foreground'>
              <Loader2 size={14} className='mr-2 animate-spin' /> {t('loading')}
            </div>
          ) : workflows.length === 0 ? (
            <p className='py-8 text-center text-xs text-muted-foreground'>
              {t('noWorkflows')}
            </p>
          ) : (
            workflows.map((wf, i) => (
              <WorkflowSection
                key={wf.workflow_id}
                wf={wf}
                defaultOpen={i === 0}
              />
            ))
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
