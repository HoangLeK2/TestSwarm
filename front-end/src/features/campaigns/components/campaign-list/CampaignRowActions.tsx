'use client';

import { Play, Pause, Square, Trash2, Eye, MoreHorizontal, Smartphone, FileText, Activity } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { DeviceControlEmbed } from '@/features/devices/components/device-control-embed';
import { AddDevicesToCampaignDialog } from '../add-devices-dialog';
import { ScenarioListDialog } from '../scenario-list-dialog';
import { CampaignRunProgress } from './CampaignRunProgress';
import { CampaignMonitorDialog } from '../campaign-monitor';
import {
  useCampaignDevices,
  useCampaignWorkflows,
  useDeleteCampaign,
  useRunCampaign,
  useScenarios,
  useUpdateCampaignStatus,
  useWorkflowCancel,
  useWorkflowPause,
  useWorkflowResume,
} from '../../hooks/use-campaigns';
import type { CampaignOut } from '../../types';
import { isIdleStatus } from '../../types';

export function CampaignRowActions({ campaign }: { campaign: CampaignOut }) {
  const t = useTranslations('campaignsFeature.list');
  const tAdd = useTranslations('campaignsFeature.addDevices');
  const tScenario = useTranslations('campaignsFeature.scenarioList');

  const { data: devices = [] } = useCampaignDevices(campaign.id);
  const { data: scenarios = [] } = useScenarios(campaign.id);

  const { mutate: updateStatus, isPending } = useUpdateCampaignStatus();
  const runMutation = useRunCampaign(
    () => toast.success(t('campaignDone')),
    { onTemporalFallback: () => toast.warning(t('temporalFallback')) }
  );
  const { mutate: runCampaign, isPending: isRunning } = runMutation;
  const { mutate: deleteCampaign, isPending: isDeleting } = useDeleteCampaign();

  const { data: wfData } = useCampaignWorkflows(campaign.id, campaign.status === 'running');
  const workflows = wfData?.workflows ?? [];
  const runningWorkflowIds = workflows.filter((w) => w.status === 'RUNNING').map((w) => w.workflow_id);
  const pausedWorkflowIds = workflows.filter((w) => w.status === 'PAUSED').map((w) => w.workflow_id);
  const hasActiveWorkflows = runningWorkflowIds.length > 0 || pausedWorkflowIds.length > 0;

  const { mutate: pauseWf, isPending: isPausing } = useWorkflowPause();
  const { mutate: resumeWf, isPending: isResuming } = useWorkflowResume();
  const { mutate: cancelWf, isPending: isCancelling } = useWorkflowCancel();

  const previewSerial = devices[0]?.serial ?? '';
  const totalSteps = scenarios.reduce((s, sc) => s + sc.steps.length, 0);
  const hasScenario = totalSteps > 0;

  const handleDelete = () => {
    if (!window.confirm(t('deleteConfirm'))) return;
    deleteCampaign(campaign.id, {
      onSuccess: () => toast.success(t('deleteSuccess')),
      onError: () => toast.error(t('deleteFailed')),
    });
  };

  const handlePauseAll = () => {
    runningWorkflowIds.forEach((id) =>
      pauseWf(id, { onError: () => toast.error(`Pause failed: ${id}`) })
    );
    toast.info(t('pausingAll', { count: runningWorkflowIds.length }));
  };

  const handleResumeAll = () => {
    pausedWorkflowIds.forEach((id) =>
      resumeWf(id, { onError: () => toast.error(`Resume failed: ${id}`) })
    );
    toast.info(t('resumingAll', { count: pausedWorkflowIds.length }));
  };

  const handleCancelAll = () => {
    if (!window.confirm(t('cancelConfirm'))) return;
    const allActive = [...runningWorkflowIds, ...pausedWorkflowIds];
    allActive.forEach((id) =>
      cancelWf(id, { onError: () => toast.error(`Cancel failed: ${id}`) })
    );
    toast.info(t('cancellingAll', { count: allActive.length }));
  };

  return (
    <div className='flex flex-col gap-1.5'>
      <div className='flex items-center gap-1'>

        {/* ── Thiết bị ── */}
        <Tooltip>
          <TooltipTrigger asChild>
            <AddDevicesToCampaignDialog
              campaignId={campaign.id}
              campaignName={campaign.name}
              deviceCount={devices.length}
            >
              <Button size='sm' variant='ghost' className='h-7 gap-1.5 px-2 text-xs'>
                <Smartphone size={13} />
                {devices.length}
              </Button>
            </AddDevicesToCampaignDialog>
          </TooltipTrigger>
          <TooltipContent side='top' className='text-xs'>
            {tAdd('trigger', { count: devices.length })}
          </TooltipContent>
        </Tooltip>

        {/* ── Kịch bản ── */}
        <Tooltip>
          <TooltipTrigger asChild>
            <ScenarioListDialog campaign={campaign}>
              <Button size='sm' variant='ghost' className='h-7 gap-1.5 px-2 text-xs'>
                <FileText size={13} />
                {scenarios.length}
              </Button>
            </ScenarioListDialog>
          </TooltipTrigger>
          <TooltipContent side='top' className='text-xs'>
            {tScenario('trigger', { scenarios: scenarios.length, steps: totalSteps })}
          </TooltipContent>
        </Tooltip>

        <div className='mx-1 h-4 w-px bg-border' />

        {/* ── Run ── */}
        {isIdleStatus(campaign.status) && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size='sm'
                variant={hasScenario ? 'default' : 'outline'}
                className='h-7 gap-1.5 px-2.5 text-xs'
                disabled={isPending || isRunning}
                onClick={() =>
                  runCampaign(campaign.id, {
                    onError: (err: unknown) => {
                      const msg =
                        err && typeof err === 'object' && 'response' in err
                          ? (err as { response?: { data?: { error?: string } } }).response?.data?.error
                          : null;
                      toast.error(msg ?? t('runFailed'));
                    },
                  })
                }
              >
                <Play size={13} />
                {t('titleRun')}
              </Button>
            </TooltipTrigger>
            {devices.length === 0 && (
              <TooltipContent side='top' className='text-xs'>
                {t('titleNeedDevice')}
              </TooltipContent>
            )}
          </Tooltip>
        )}

        {/* ── Running controls ── */}
        {campaign.status === 'running' && (
          <>
            {/* Monitor button */}
            <Tooltip>
              <TooltipTrigger asChild>
                <CampaignMonitorDialog campaign={campaign}>
                  <Button size='sm' variant='ghost' className='h-7 gap-1 px-2 text-xs text-blue-600 hover:text-blue-600 hover:bg-blue-500/10'>
                    <Activity size={13} />
                  </Button>
                </CampaignMonitorDialog>
              </TooltipTrigger>
              <TooltipContent side='top' className='text-xs'>Theo dõi từng bước</TooltipContent>
            </Tooltip>

            {runningWorkflowIds.length > 0 && (
              <Button
                size='sm'
                variant='outline'
                className='h-7 gap-1.5 px-2.5 text-xs'
                disabled={isPausing}
                onClick={handlePauseAll}
              >
                <Pause size={13} />
                {t('titlePause')}
              </Button>
            )}
            {pausedWorkflowIds.length > 0 && (
              <Button
                size='sm'
                variant='outline'
                className='h-7 gap-1.5 px-2.5 text-xs text-green-600 hover:text-green-600'
                disabled={isResuming}
                onClick={handleResumeAll}
              >
                <Play size={13} />
                {t('titleResume')}
              </Button>
            )}
            {hasActiveWorkflows && (
              <Button
                size='sm'
                variant='ghost'
                className='h-7 px-2 text-xs text-destructive hover:text-destructive'
                disabled={isCancelling}
                onClick={handleCancelAll}
              >
                <Square size={13} />
              </Button>
            )}
            {/* Live preview */}
            {previewSerial && (
              <Dialog>
                <DialogTrigger asChild>
                  <Button size='sm' variant='ghost' className='h-7 gap-1.5 px-2 text-xs'>
                    <Eye size={13} />
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
          </>
        )}

        {/* ── More ── */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size='sm' variant='ghost' className='h-7 w-7 p-0'>
              <MoreHorizontal size={14} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align='end' className='w-44'>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className='gap-2 text-destructive focus:text-destructive'
              disabled={isDeleting}
              onClick={handleDelete}
            >
              <Trash2 size={13} />
              {t('titleDelete')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* ── Progress ── */}
      <CampaignRunProgress
        campaignId={campaign.id}
        isRunning={campaign.status === 'running'}
        executionEngineHint={
          runMutation.data?.execution_engine ?? runMutation.data?.engine ?? undefined
        }
      />
    </div>
  );
}
