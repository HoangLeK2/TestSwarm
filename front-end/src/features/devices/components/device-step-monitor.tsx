'use client';

import { useState } from 'react';
import { Activity, ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
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
import { useWorkflowRecoveryState } from '@/features/campaigns/hooks/use-workflow-recovery-state';
import { WorkflowScenarioModeBadge } from '@/features/campaigns/components/workflow-scenario-mode-badge';
import {
  parseWorkflowId,
  WorkflowStepList
} from '@/features/campaigns/components/workflow-step-list';
import type { WorkflowInfo } from '@/features/campaigns/types';

function workflowStatusLabel(
  status: string,
  tCampaign: ReturnType<typeof useTranslations<'campaignsFeature.list'>>
): string {
  if (status === 'RUNNING') return tCampaign('monitorStatusRunningLabel');
  if (status === 'PAUSED') return status;
  if (status === 'COMPLETED') return status;
  if (status === 'FAILED') return status;
  return status;
}

function WorkflowStatusBadge({ status }: { status: string }) {
  const tCampaign = useTranslations('campaignsFeature.list');

  return (
    <Badge
      variant='outline'
      className={cn(
        'h-5 gap-1.5 px-2 text-[10px] font-semibold uppercase tracking-wide',
        status === 'RUNNING' && 'border-primary/40 bg-primary/5 text-primary',
        status === 'COMPLETED' &&
          'border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-400',
        status === 'FAILED' &&
          'border-destructive/30 bg-destructive/10 text-destructive',
        status === 'PAUSED' &&
          'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300'
      )}
    >
      {status === 'RUNNING' ? (
        <span className='relative flex size-1.5'>
          <span className='absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-60' />
          <span className='relative inline-flex size-1.5 rounded-full bg-primary' />
        </span>
      ) : null}
      {workflowStatusLabel(status, tCampaign)}
    </Badge>
  );
}

function WorkflowSection({
  wf,
  defaultOpen
}: {
  wf: WorkflowInfo;
  defaultOpen?: boolean;
}) {
  const tCampaign = useTranslations('campaignsFeature.list');
  const [open, setOpen] = useState(defaultOpen ?? true);
  const parsed = parseWorkflowId(wf.workflow_id);
  const campaignId = wf.campaign_id || parsed.campaignId;
  const scenarioId = wf.scenario_id || parsed.scenarioId;
  const campaignLabel =
    wf.campaign_name ||
    (campaignId
      ? `#${campaignId.slice(0, 8)}`
      : tCampaign('monitorWorkflowUnknownCampaign'));
  const scenarioLabel =
    wf.scenario_name ||
    (wf.scenario_count && wf.scenario_count > 1
      ? tCampaign('monitorWorkflowScenarioCount', { count: wf.scenario_count })
      : scenarioId
        ? `#${scenarioId.slice(0, 8)}`
        : tCampaign('monitorWorkflowUnknownScenario'));
  const executionLabel = wf.execution_id
    ? tCampaign('monitorWorkflowExecutionShort', {
        id: wf.execution_id.slice(0, 8)
      })
    : null;
  const { isRecoveryMode, recoveryScenarioName, eventStream } =
    useWorkflowRecoveryState(wf, { enabled: open });

  return (
    <div className='overflow-hidden rounded-lg border bg-card'>
      <button
        type='button'
        className='flex w-full items-start gap-2 px-3 py-3 text-left transition-colors hover:bg-accent/20'
        onClick={() => setOpen((v) => !v)}
      >
        <span className='mt-0.5 shrink-0 text-muted-foreground'>
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <span className='min-w-0 flex-1'>
          <span className='flex min-w-0 items-center gap-2'>
            <span
              className='truncate text-sm font-semibold text-foreground'
              title={wf.campaign_name || campaignId || wf.workflow_id}
            >
              {campaignLabel}
            </span>
            <WorkflowScenarioModeBadge
              mode={isRecoveryMode ? 'recovery' : 'main'}
              scenarioName={recoveryScenarioName}
            />
          </span>
          <span className='mt-1 flex min-w-0 flex-wrap items-center gap-1 text-[10px] text-muted-foreground'>
            <span
              className='truncate'
              title={wf.scenario_name || scenarioId || undefined}
            >
              {scenarioLabel}
            </span>
            {executionLabel ? (
              <>
                <span className='text-muted-foreground/50'>·</span>
                <span className='shrink-0 font-mono'>{executionLabel}</span>
              </>
            ) : null}
          </span>
        </span>
        <WorkflowStatusBadge status={wf.status} />
      </button>
      {open ? (
        <div className='border-t px-3 py-3'>
          <WorkflowStepList
            wf={wf}
            maxHeight='min(480px, calc(100dvh - 280px))'
            sseStepLog={eventStream.stepLog}
            sseConnected={eventStream.connected}
            liveProgress={
              eventStream.progress
                ? {
                    current_step: eventStream.progress.current_step ?? 0,
                    total_steps: eventStream.progress.total_steps ?? 0,
                    current_step_type:
                      eventStream.progress.current_step_type ?? '',
                    current_step_id:
                      eventStream.progress.current_step_id ?? null,
                    current_step_path:
                      eventStream.progress.current_step_path ?? null,
                    current_loop_iter:
                      eventStream.progress.current_loop_iter ??
                      eventStream.progress.loop_iteration ??
                      null,
                    reason_code: eventStream.progress.reason_code ?? null,
                    message: eventStream.progress.message ?? '',
                    loop_iteration: eventStream.progress.loop_iteration ?? null
                  }
                : undefined
            }
          />
        </div>
      ) : null}
    </div>
  );
}

export function DeviceStepsPanel({ serial }: { serial: string }) {
  const t = useTranslations('devicesFarm.stepMonitor');
  const { data, isLoading } = useDeviceRunningWorkflows(serial, true);
  const workflows = data?.workflows ?? [];

  return (
    <div className='flex flex-col gap-3'>
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
  const hasLiveWorkflow = workflows.some((wf) => wf.status === 'RUNNING');

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side='right'
        className='flex w-full flex-col gap-0 p-0 sm:max-w-md'
      >
        <SheetHeader className='border-b px-4 py-3.5 text-left'>
          <div className='flex items-start gap-3'>
            <div className='flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10'>
              <Activity size={16} className='text-primary' />
            </div>
            <div className='min-w-0 flex-1'>
              <SheetTitle className='text-sm font-semibold'>
                {t('title')}
              </SheetTitle>
              {serial ? (
                <p className='mt-0.5 font-mono text-[10px] text-muted-foreground'>
                  {serial}
                </p>
              ) : null}
            </div>
            {hasLiveWorkflow ? (
              <Badge className='h-5 shrink-0 bg-primary/15 px-2 text-[10px] text-primary hover:bg-primary/15'>
                {t('live')}
              </Badge>
            ) : null}
          </div>
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
