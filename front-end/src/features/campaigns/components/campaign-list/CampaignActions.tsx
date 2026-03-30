'use client';

import { Play, Pause, Square, CheckCircle, Trash2, Zap, Eye } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { DeviceControlEmbed } from '@/features/devices/components/device-control-embed';
import {
  useCampaignDevices,
  useCampaignWorkflows,
  useDeleteCampaign,
  useFleetRunCampaign,
  useRunCampaign,
  useUpdateCampaignStatus,
  useWorkflowCancel,
  useWorkflowPause,
  useWorkflowResume,
} from '../../hooks/use-campaigns';
import type { CampaignOut } from '../../types';
import { CampaignRunProgress } from './CampaignRunProgress';

export function CampaignActions({ campaign }: { campaign: CampaignOut }) {
  const t = useTranslations('campaignsFeature.list');
  const { mutate: updateStatus, isPending } = useUpdateCampaignStatus();
  const runMutation = useRunCampaign(
    () => {
      toast.success(t('campaignDone'));
    },
    {
      onTemporalFallback: () => toast.warning(t('temporalFallback'))
    }
  );
  const { mutate: runCampaign, isPending: isRunning } = runMutation;
  const { mutate: fleetRun, isPending: isFleetRunning } = useFleetRunCampaign((result) => {
    toast.success(t('fleetDone', { done: result.done, total: result.total }));
  });
  const { mutate: deleteCampaign, isPending: isDeleting } = useDeleteCampaign();
  const { data: devices = [] } = useCampaignDevices(campaign.id);

  // Temporal workflow controls
  const { data: wfData } = useCampaignWorkflows(campaign.id, campaign.status === 'running');
  const workflows = wfData?.workflows ?? [];
  const runningWorkflowIds = workflows.filter((w) => w.status === 'RUNNING').map((w) => w.workflow_id);
  const pausedWorkflowIds = workflows.filter((w) => w.status === 'PAUSED').map((w) => w.workflow_id);
  const hasActiveWorkflows = runningWorkflowIds.length > 0 || pausedWorkflowIds.length > 0;

  const { mutate: pauseWf, isPending: isPausing } = useWorkflowPause();
  const { mutate: resumeWf, isPending: isResuming } = useWorkflowResume();
  const { mutate: cancelWf, isPending: isCancelling } = useWorkflowCancel();

  const deviceCount = devices.length;
  const previewSerial = devices[0]?.serial ?? '';

  const hasScenario =
    (Array.isArray(campaign.scenarios) && campaign.scenarios.some((s) => s.steps?.length > 0)) ||
    (Array.isArray(campaign.scenario?.steps) && (campaign.scenario?.steps?.length ?? 0) > 0);

  const handleDelete = () => {
    if (!window.confirm(t('deleteConfirm'))) return;
    deleteCampaign(campaign.id, {
      onSuccess: () => toast.success(t('deleteSuccess')),
      onError: () => toast.error(t('deleteFailed'))
    });
  };

  const handleFleetRun = () => {
    if (!hasScenario) {
      toast.error(t('missingScenario'));
      return;
    }
    fleetRun(campaign, {
      onError: (err: unknown) => {
        const msg = err instanceof Error ? err.message : t('fleetFailed');
        toast.error(msg);
      }
    });
  };

  const handlePauseAll = () => {
    runningWorkflowIds.forEach((id) =>
      pauseWf(id, { onError: () => toast.error(`Pause failed: ${id}`) })
    );
    toast.info(`Pausing ${runningWorkflowIds.length} workflow(s)...`);
  };

  const handleResumeAll = () => {
    pausedWorkflowIds.forEach((id) =>
      resumeWf(id, { onError: () => toast.error(`Resume failed: ${id}`) })
    );
    toast.info(`Resuming ${pausedWorkflowIds.length} workflow(s)...`);
  };

  const handleCancelAll = () => {
    if (!window.confirm(t('cancelConfirm', { fallback: 'Cancel all running workflows?' }))) return;
    const allActive = [...runningWorkflowIds, ...pausedWorkflowIds];
    allActive.forEach((id) =>
      cancelWf(id, { onError: () => toast.error(`Cancel failed: ${id}`) })
    );
    toast.info(`Cancelling ${allActive.length} workflow(s)...`);
  };

  return (
    <div className='flex flex-col gap-1'>
      <div className='flex gap-1'>
        {/* Run / Re-run */}
        {(campaign.status === 'draft' || campaign.status === 'paused' || campaign.status === 'completed') && (
          <Button
            size='icon'
            variant='ghost'
            className='size-7'
            disabled={isPending || isRunning}
            onClick={() =>
              runCampaign(campaign.id, {
                onError: (err: unknown) => {
                  const msg =
                    err && typeof err === 'object' && 'response' in err
                      ? (err as { response?: { data?: { error?: string } } }).response?.data?.error
                      : null;
                  toast.error(msg ?? t('runFailed'));
                }
              })
            }
            title={deviceCount === 0 ? t('titleNeedDevice') : campaign.status === 'paused' ? t('titleResume') : t('titleRun')}
          >
            <Play size={12} />
          </Button>
        )}

        {/* Temporal workflow controls when running */}
        {campaign.status === 'running' && (
          <>
            {/* Pause all running workflows */}
            {runningWorkflowIds.length > 0 && (
              <Button
                size='icon'
                variant='ghost'
                className='size-7'
                disabled={isPausing}
                onClick={handlePauseAll}
                title={`Pause ${runningWorkflowIds.length} workflow(s)`}
              >
                <Pause size={12} />
              </Button>
            )}

            {/* Resume paused workflows */}
            {pausedWorkflowIds.length > 0 && (
              <Button
                size='icon'
                variant='ghost'
                className='size-7 text-green-500'
                disabled={isResuming}
                onClick={handleResumeAll}
                title={`Resume ${pausedWorkflowIds.length} workflow(s)`}
              >
                <Play size={12} />
              </Button>
            )}

            {/* Cancel all */}
            {hasActiveWorkflows && (
              <Button
                size='icon'
                variant='ghost'
                className='size-7 text-destructive'
                disabled={isCancelling}
                onClick={handleCancelAll}
                title='Cancel all workflows'
              >
                <Square size={12} />
              </Button>
            )}

            {/* Fallback: mark completed (legacy or when no workflows) */}
            {!hasActiveWorkflows && (
              <Button
                size='icon'
                variant='ghost'
                className='size-7'
                disabled={isPending}
                onClick={() =>
                  updateStatus(
                    { id: campaign.id, status: 'completed' },
                    { onSuccess: () => toast.success(t('markedDone')) }
                  )
                }
                title={t('titleComplete')}
              >
                <CheckCircle size={12} />
              </Button>
            )}
          </>
        )}

        {/* Fleet run */}
        {hasScenario && campaign.status !== 'running' && (
          <Button
            size='icon'
            variant='ghost'
            className='size-7 text-amber-500 hover:text-amber-500'
            disabled={isFleetRunning || isRunning}
            onClick={handleFleetRun}
            title={t('titleFleet')}
          >
            <Zap size={12} />
          </Button>
        )}

        <Button
          size='icon'
          variant='ghost'
          className='size-7 text-destructive hover:text-destructive'
          disabled={isDeleting}
          onClick={handleDelete}
          title={t('titleDelete')}
        >
          <Trash2 size={12} />
        </Button>
      </div>

      <CampaignRunProgress
        campaignId={campaign.id}
        isRunning={campaign.status === 'running'}
        executionEngineHint={
          runMutation.data?.execution_engine ?? runMutation.data?.engine ?? undefined
        }
      />

      {campaign.status === 'running' && previewSerial && (
        <Dialog>
          <DialogTrigger asChild>
            <Button
              size='sm'
              variant='outline'
              className='h-7 gap-1 text-[11px]'
              title={t('titleLivePreview')}
            >
              <Eye size={12} />
              Live
            </Button>
          </DialogTrigger>
          <DialogContent className='max-w-[420px]'>
            <DialogHeader>
              <DialogTitle className='text-sm'>{t('liveDialogTitle')}</DialogTitle>
            </DialogHeader>
            <DeviceControlEmbed initialSerial={previewSerial} compact />
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
