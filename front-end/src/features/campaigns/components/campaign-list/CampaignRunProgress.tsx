'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Progress } from '@/components/ui/progress';
import {
  useCampaignProgress,
  useCampaignWorkflows,
} from '../../hooks/use-campaigns';
import type { CampaignExecutionEngine, WorkflowInfo } from '../../types';

const _dfEngineKey = (campaignId: string) => `df_campaign_engine:${campaignId}`;

function WorkflowRow({ wf }: { wf: WorkflowInfo }) {
  // Extract device serial from workflow_id: "campaign:...:device:SERIAL:scenario:..."
  const parts = wf.workflow_id.split(':');
  const deviceIdx = parts.indexOf('device');
  const serial = deviceIdx >= 0 ? parts[deviceIdx + 1] : wf.workflow_id;

  const statusColor: Record<string, string> = {
    RUNNING: 'text-blue-500',
    COMPLETED: 'text-green-500',
    FAILED: 'text-destructive',
    CANCELLED: 'text-muted-foreground',
    PAUSED: 'text-amber-500',
    TERMINATED: 'text-destructive',
  };

  return (
    <div className='flex items-center gap-2 text-[10px]'>
      <span className='font-mono truncate max-w-[140px]' title={serial}>
        {serial}
      </span>
      <span className={statusColor[wf.status] ?? 'text-muted-foreground'}>
        {wf.status}
      </span>
    </div>
  );
}

export function CampaignRunProgress({
  campaignId,
  isRunning,
  executionEngineHint,
}: {
  campaignId: string;
  isRunning: boolean;
  executionEngineHint?: CampaignExecutionEngine | null;
}) {
  const t = useTranslations('campaignsFeature.list');
  const [storedEngine, setStoredEngine] = useState<CampaignExecutionEngine | null>(null);

  useEffect(() => {
    if (!isRunning) {
      setStoredEngine(null);
      return;
    }
    try {
      const v = sessionStorage.getItem(_dfEngineKey(campaignId));
      setStoredEngine(v === 'temporal' || v === 'task_queue' ? v : null);
    } catch {
      setStoredEngine(null);
    }
  }, [campaignId, isRunning]);

  // Temporal workflows
  const { data: wfData } = useCampaignWorkflows(campaignId, isRunning);
  const workflows = wfData?.workflows ?? [];

  // Legacy task progress (fallback)
  const { data: legacyProgress } = useCampaignProgress(campaignId, isRunning && workflows.length === 0);

  if (!isRunning) return null;

  const engineLabel: CampaignExecutionEngine | null =
    executionEngineHint ??
    storedEngine ??
    (workflows.length > 0 ? 'temporal' : legacyProgress && legacyProgress.total > 0 ? 'task_queue' : null);

  // Temporal mode
  if (workflows.length > 0) {
    const total = workflows.length;
    const completed = workflows.filter((w) => w.status === 'COMPLETED').length;
    const failed = workflows.filter((w) => w.status === 'FAILED' || w.status === 'CANCELLED' || w.status === 'TERMINATED').length;
    const running = workflows.filter((w) => w.status === 'RUNNING').length;
    const paused = workflows.filter((w) => w.status === 'PAUSED').length;
    const terminal = completed + failed;
    const pct = total ? Math.round((terminal / total) * 100) : 0;

    return (
      <div className='flex flex-col gap-1'>
        <div className='flex items-center gap-2 text-[10px] text-muted-foreground'>
          <span className='font-medium tabular-nums text-foreground'>{completed}/{total}</span>
          {running > 0 && <span className='text-blue-500'>{t('wfRunning', { count: running })}</span>}
          {paused > 0 && <span className='text-amber-500'>{t('wfPaused', { count: paused })}</span>}
          {failed > 0 && <span className='text-destructive'>{t('wfFailed', { count: failed })}</span>}
          <span className='ml-auto tabular-nums'>{pct}%</span>
        </div>
        <Progress value={pct} className='h-1' />
      </div>
    );
  }

  // Legacy fallback
  if (!legacyProgress || legacyProgress.total === 0) return null;

  return (
    <div className='flex flex-col gap-1'>
      <div className='flex items-center gap-2 text-[10px] text-muted-foreground'>
        <span className='font-medium text-foreground'>
          {t('progressDone', { done: legacyProgress.done, total: legacyProgress.total })}
        </span>
        {legacyProgress.failed > 0 && (
          <span className='text-destructive'>{t('progressFailed', { count: legacyProgress.failed })}</span>
        )}
        <span className='ml-auto tabular-nums'>{legacyProgress.pct}%</span>
      </div>
      <Progress value={legacyProgress.pct} className='h-1' />
    </div>
  );
}
