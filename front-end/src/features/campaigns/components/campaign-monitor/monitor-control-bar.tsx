'use client';

import { Loader2, Pause, Play, Square } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  useCampaignCancel,
  useCampaignPause,
  useCampaignResume,
  useCampaignStopDrain,
  useCampaignWorkflows
} from '../../hooks/use-campaigns';
import type { CampaignOut } from '../../types';
import { isCampaignActiveExecution } from '../../types';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { useConfirm } from '@/providers/modal-provider';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';

interface Props {
  campaign: CampaignOut;
}

export function MonitorControlBar({ campaign }: Props) {
  const t = useTranslations('campaignsFeature.list');
  const tCommon = useTranslations('common');
  const confirm = useConfirm();
  const { canExecute } = useResourcePermissions('campaigns');

  const { isStopping, activeWorkflowCount, activeExecutionCount } =
    useCampaignStopDrain(campaign.id, campaign.status);
  const running =
    isCampaignActiveExecution(campaign.status) || isStopping;
  const { data: wfData } = useCampaignWorkflows(campaign.id, running);
  const workflows = wfData?.workflows ?? [];

  const runningCount = workflows.filter((w) => w.status === 'RUNNING').length;
  const pausedCount = workflows.filter(
    (w) => w.status === 'PAUSED' || w.status === 'paused_on_error'
  ).length;

  const { mutate: pauseCampaign, isPending: isPausing } = useCampaignPause();
  const { mutate: resumeCampaign, isPending: isResuming } = useCampaignResume();
  const { mutateAsync: cancelCampaign, isPending: isCancelling } =
    useCampaignCancel();

  if (!canExecute || !running) {
    return null;
  }

  const showPause =
    !isStopping &&
    campaign.status === 'running' &&
    runningCount > 0;
  const showResume =
    !isStopping &&
    (campaign.status === 'paused' || pausedCount > 0);

  const handleCancelAll = async () => {
    const ok = await confirm({
      title: t('titleCancelAll'),
      description: `${t('cancelConfirm')}\n\n${t('cancelUndoWarning')}`,
      confirmText: tCommon('confirm'),
      cancelText: tCommon('cancel'),
      confirmVariant: 'destructive',
      zIndex: 10_000
    });
    if (!ok) return;
    try {
      const data = await cancelCampaign({ campaignId: campaign.id });
      toast.success(t('cancelSuccess'));
      if ((data.workflows_signalled ?? 0) > 0) {
        toast.info(
          t('cancellingAll', { count: data.workflows_signalled ?? 0 })
        );
      }
    } catch (err) {
      toast.error(formatFarmApiError(err, t('cancelFailed')));
    }
  };

  return (
    <div className='flex shrink-0 flex-wrap items-center gap-1.5 border-t bg-muted/30 px-6 py-2'>
      <span className='mr-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
        {t('monitorControlLabel')}
      </span>
      {isStopping ? (
        <span className='inline-flex items-center gap-1.5 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-800 dark:text-amber-200'>
          <Loader2 className='size-3 animate-spin' aria-hidden />
          {t('stoppingDetail', {
            workflows: activeWorkflowCount,
            executions: activeExecutionCount
          })}
        </span>
      ) : null}
      {showPause ? (
        <Button
          size='sm'
          variant='outline'
          className='h-7 gap-1 px-2 text-[11px]'
          disabled={isPausing}
          onClick={() =>
            pauseCampaign(campaign.id, {
              onSuccess: (data) =>
                toast.info(
                  t('pausingAll', { count: data.workflows_signalled ?? 0 })
                ),
              onError: (err) =>
                toast.error(formatFarmApiError(err, t('runFailed')))
            })
          }
        >
          <Pause size={12} />
          {t('titlePause')}
        </Button>
      ) : null}
      {showResume ? (
        <Button
          size='sm'
          variant='outline'
          className='h-7 gap-1 px-2 text-[11px] text-green-600 hover:text-green-600'
          disabled={isResuming}
          onClick={() =>
            resumeCampaign(campaign.id, {
              onSuccess: () =>
                toast.info(t('resumingAll', { count: pausedCount || 1 })),
              onError: (err) =>
                toast.error(formatFarmApiError(err, t('runFailed')))
            })
          }
        >
          <Play size={12} />
          {t('titleResume')}
        </Button>
      ) : null}
      <Button
        size='sm'
        variant='ghost'
        className='h-7 gap-1 px-2 text-[11px] text-destructive hover:text-destructive'
        disabled={isCancelling || isStopping}
        onClick={() => void handleCancelAll()}
      >
        <Square size={12} />
        {t('titleCancelAll')}
      </Button>
    </div>
  );
}
