'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Activity, CheckCircle2, Circle, Loader2, XCircle,
  ChevronDown, ChevronRight, AlertCircle,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog';
import { Progress } from '@/components/ui/progress';
import {
  useDeviceRunningWorkflows,
  useWorkflowProgress,
  useWorkflowSteps,
} from '@/features/campaigns/hooks/use-campaigns';
import { scenariosApi } from '@/features/campaigns/services/api';
import { getStepTypeName, getStepDisplay } from '@/features/campaigns/components/flow-editor/constants';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import type { WorkflowInfo, StepLogEntry } from '@/features/campaigns/types';

// ── Parse workflow ID ─────────────────────────────────────────────────────────

function parseWorkflowId(id: string) {
  const m = id.match(/^campaign:([^:]+):device:.+:scenario:([^:]+)$/);
  return { campaignId: m?.[1] ?? '', scenarioId: m?.[2] ?? '' };
}

// ── Step row ──────────────────────────────────────────────────────────────────

function StepRow({
  index,
  stepDef,
  logEntry,
  isCurrentlyRunning,
  currentStepType,
  currentMessage,
  loopIter,
  isPending,
}: {
  index: number;
  stepDef?: FlowStep;
  logEntry?: StepLogEntry;
  isCurrentlyRunning: boolean;
  currentStepType: string;
  currentMessage: string;
  loopIter: number | null;
  isPending: boolean;
}) {
  const type = stepDef?.type ?? logEntry?.step_type ?? (isCurrentlyRunning ? currentStepType : '');
  const userTitle = (stepDef as any)?.title?.trim() || undefined;
  const { target } = stepDef ? getStepDisplay(stepDef) : { target: '' };
  const label = userTitle ?? (type ? getStepTypeName(type) : `Bước ${index + 1}`);
  const sublabel = !userTitle && target ? target : undefined;
  const depth = logEntry?.depth ?? 0;

  // Status
  const isDone = !!logEntry && !isCurrentlyRunning;
  const isFailed = isDone && !logEntry.ok;
  const isOk = isDone && logEntry.ok;
  const msg = isCurrentlyRunning ? currentMessage : (logEntry?.message ?? '');

  return (
    <div
      className={cn(
        'flex items-start gap-2 border-b last:border-b-0 py-2 pr-3 text-[11px] transition-colors',
        isCurrentlyRunning && 'bg-primary/5',
        isFailed && 'bg-destructive/5',
        isPending && 'opacity-40',
      )}
      style={{ paddingLeft: `${12 + depth * 14}px` }}
    >
      {/* Icon */}
      <div className='mt-0.5 w-3 shrink-0'>
        {isFailed ? (
          <XCircle size={12} className='text-destructive' />
        ) : isCurrentlyRunning ? (
          <Loader2 size={12} className='animate-spin text-primary' />
        ) : isOk ? (
          <CheckCircle2 size={12} className='text-green-500' />
        ) : (
          <Circle size={12} className='text-muted-foreground/25' />
        )}
      </div>

      {/* Number */}
      <span className={cn(
        'mt-0.5 w-5 shrink-0 tabular-nums text-[10px]',
        isCurrentlyRunning ? 'font-bold text-primary' : 'text-muted-foreground',
      )}>
        {index + 1}
      </span>

      {/* Name + sublabel + message */}
      <div className='min-w-0 flex-1'>
        <div className={cn(
          'truncate leading-tight',
          isCurrentlyRunning ? 'font-semibold text-primary' : isFailed ? 'text-destructive' : isOk ? 'text-foreground' : 'text-muted-foreground/60',
        )}>
          {label}
        </div>
        {sublabel && !isCurrentlyRunning && (
          <div className='truncate text-[10px] text-muted-foreground' title={sublabel}>{sublabel}</div>
        )}
        {isCurrentlyRunning && msg && (
          <div className='truncate text-[10px] italic text-primary/70' title={msg}>{msg}</div>
        )}
        {isCurrentlyRunning && loopIter !== null && (
          <div className='text-[10px] text-primary/60'>Vòng #{loopIter + 1}</div>
        )}
        {isFailed && msg && (
          <div className='truncate text-[10px] text-destructive/80' title={msg}>{msg}</div>
        )}
      </div>

      {/* Type badge */}
      {type && (
        <span className={cn(
          'mt-0.5 shrink-0 rounded px-1 py-px text-[9px] font-bold uppercase tracking-wide',
          isCurrentlyRunning ? 'bg-primary/15 text-primary'
            : isOk ? 'bg-green-500/10 text-green-600 dark:text-green-400'
            : isFailed ? 'bg-destructive/10 text-destructive'
            : 'bg-muted text-muted-foreground/50',
        )}>
          {getStepTypeName(type)}
        </span>
      )}
    </div>
  );
}

// ── Step list for one workflow ────────────────────────────────────────────────

function WorkflowStepList({ wf }: { wf: WorkflowInfo }) {
  const isActive = wf.status === 'RUNNING' || wf.status === 'PAUSED';
  const { campaignId, scenarioId } = parseWorkflowId(wf.workflow_id);

  // 1. Live progress (current step index + type)
  const { data: prog } = useWorkflowProgress(wf.workflow_id, isActive);

  // 2. Step execution log (executed steps with ok/fail)
  const { data: stepLog, isLoading: logLoading } = useWorkflowSteps(wf.workflow_id, true);

  // 3. Scenario step definitions (type names, titles, values)
  const { data: scenario, isLoading: scenarioLoading } = useQuery({
    queryKey: ['scenario-steps', campaignId, scenarioId],
    queryFn: () => scenariosApi.get(campaignId, scenarioId),
    enabled: !!campaignId && !!scenarioId,
    staleTime: 30_000,
  });

  if (logLoading || scenarioLoading) {
    return (
      <div className='flex items-center gap-2 py-4 text-xs text-muted-foreground'>
        <Loader2 size={12} className='animate-spin' /> Đang tải...
      </div>
    );
  }

  const scenarioDefs: FlowStep[] = (scenario?.steps ?? []) as FlowStep[];
  const executedSteps: StepLogEntry[] = stepLog?.steps ?? [];

  const current = prog?.current_step ?? 0;
  const total = prog?.total_steps ?? scenarioDefs.length ?? executedSteps.length;
  const stepType = prog?.current_step_type ?? '';
  const message = prog?.message ?? '';
  const loopIter = prog?.loop_iteration != null && prog.loop_iteration >= 0 ? prog.loop_iteration : null;
  const pct = total > 0
    ? Math.round(((isActive ? current : executedSteps.length) / total) * 100)
    : wf.status === 'COMPLETED' ? 100 : 0;

  // Build a merged row list: scenario defs drive the list; log entries enrich each row
  const logByIndex = new Map(executedSteps.map((e) => [e.index, e]));
  const rowCount = Math.max(total, scenarioDefs.length, executedSteps.length > 0 ? (executedSteps[executedSteps.length - 1]?.index ?? 0) + 1 : 0);

  return (
    <div className='space-y-3'>
      {/* Progress bar */}
      <div className='flex items-center gap-2'>
        <Progress
          value={pct}
          className={cn(
            'h-1.5 flex-1',
            wf.status === 'FAILED' && '[&>div]:bg-destructive',
            wf.status === 'PAUSED' && '[&>div]:bg-amber-500',
            wf.status === 'COMPLETED' && '[&>div]:bg-green-500',
          )}
        />
        <span className='shrink-0 tabular-nums text-[10px] text-muted-foreground'>
          {isActive ? `${current}/${total}` : `${executedSteps.length}/${total}`}
        </span>
      </div>

      {/* Step list */}
      {rowCount > 0 ? (
        <div className='overflow-hidden rounded-md border bg-background'>
          <div className='max-h-[400px] overflow-y-auto'>
            {Array.from({ length: rowCount }).map((_, i) => {
              const logEntry = logByIndex.get(i);
              const stepDef = scenarioDefs[i];
              const isCurrentlyRunning = isActive && i === current && !logEntry;

              return (
                <StepRow
                  key={i}
                  index={i}
                  stepDef={stepDef}
                  logEntry={logEntry}
                  isCurrentlyRunning={isCurrentlyRunning}
                  currentStepType={stepType}
                  currentMessage={message}
                  loopIter={loopIter}
                  isPending={!logEntry && !isCurrentlyRunning && i > current}
                />
              );
            })}
          </div>
        </div>
      ) : (
        <p className='text-center text-[11px] text-muted-foreground py-4'>Chưa có dữ liệu bước.</p>
      )}

      {/* Summary */}
      {wf.status === 'COMPLETED' && (
        <div className='flex items-center gap-1.5 text-[11px] text-green-600 dark:text-green-400'>
          <CheckCircle2 size={12} /> Hoàn thành {executedSteps.length} bước
        </div>
      )}
      {wf.status === 'FAILED' && (
        <div className='flex items-center gap-1.5 text-[11px] text-destructive'>
          <AlertCircle size={12} />
          {message || `Thất bại tại bước ${current + 1}`}
        </div>
      )}
    </div>
  );
}

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
