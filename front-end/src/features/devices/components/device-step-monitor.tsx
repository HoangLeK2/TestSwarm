'use client';

import { useState } from 'react';
import {
  Activity, ChevronDown, ChevronRight,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog';
import { Loader2 } from 'lucide-react';
import {
  useDeviceRunningWorkflows,
} from '@/features/campaigns/hooks/use-campaigns';
import { parseWorkflowId, WorkflowStepList } from '@/features/campaigns/components/workflow-step-list';
import type { WorkflowInfo } from '@/features/campaigns/types';

// ── Accordion per workflow ────────────────────────────────────────────────────

function WorkflowSection({ wf, defaultOpen }: { wf: WorkflowInfo; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen ?? true);
  const { campaignId } = parseWorkflowId(wf.workflow_id);

  const statusColor: Record<string, string> = {
    RUNNING: 'text-blue-500', COMPLETED: 'text-green-500',
    FAILED: 'text-destructive', PAUSED: 'text-amber-500',
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
          Campaign <span className='font-mono font-semibold text-foreground'>#{campaignId.slice(0, 8)}</span>
        </span>
        <span className={cn('text-[10px] font-bold', statusColor[wf.status] ?? 'text-muted-foreground')}>
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
  const { data, isLoading } = useDeviceRunningWorkflows(serial, true);
  const workflows = data?.workflows ?? [];

  return (
    <div className='flex flex-col gap-2'>
      {isLoading && (
        <div className='flex items-center justify-center py-8 text-xs text-muted-foreground'>
          <Loader2 size={14} className='mr-2 animate-spin' /> Đang tải...
        </div>
      )}
      {!isLoading && workflows.length === 0 && (
        <p className='py-8 text-center text-xs text-muted-foreground'>
          Không có workflow đang chạy.
        </p>
      )}
      {workflows.map((wf, i) => (
        <WorkflowSection key={wf.workflow_id} wf={wf} defaultOpen={i === 0} />
      ))}
    </div>
  );
}

// ── Main dialog ───────────────────────────────────────────────────────────────

interface Props {
  serial: string;
  isBusy: boolean;
}

export function DeviceStepMonitor({ serial, isBusy }: Props) {
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useDeviceRunningWorkflows(serial, open);
  const workflows = data?.workflows ?? [];

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          size='sm'
          variant={isBusy ? 'outline' : 'ghost'}
          className={isBusy
            ? 'h-7 gap-1.5 px-2.5 text-[11px] text-blue-600 border-blue-400/50 hover:bg-blue-50 dark:hover:bg-blue-950/30'
            : 'h-7 gap-1 px-2 text-[11px] text-muted-foreground'
          }
        >
          <Activity size={12} className={isBusy ? 'animate-pulse' : ''} />
          {isBusy ? 'Đang chạy' : 'Steps'}
        </Button>
      </DialogTrigger>

      <DialogContent className='max-w-md p-0 gap-0'>
        <DialogHeader className='border-b px-4 py-3'>
          <div className='flex items-center gap-2'>
            <Activity size={14} className='text-primary' />
            <DialogTitle className='text-sm font-semibold'>Theo dõi bước</DialogTitle>
          </div>
          <p className='mt-0.5 font-mono text-[10px] text-muted-foreground'>{serial}</p>
        </DialogHeader>

        <div className='max-h-[75vh] space-y-3 overflow-y-auto p-4'>
          {isLoading && (
            <div className='flex items-center justify-center py-8 text-xs text-muted-foreground'>
              <Loader2 size={14} className='mr-2 animate-spin' /> Đang tải...
            </div>
          )}
          {!isLoading && workflows.length === 0 && (
            <p className='py-8 text-center text-xs text-muted-foreground'>
              Không có workflow đang chạy.
            </p>
          )}
          {workflows.map((wf, i) => (
            <WorkflowSection key={wf.workflow_id} wf={wf} defaultOpen={i === 0} />
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
