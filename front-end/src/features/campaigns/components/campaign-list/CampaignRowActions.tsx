'use client';

import { useState } from 'react';
import { Play, Pause, Square, Trash2, Eye, MoreHorizontal, Smartphone, FileText, BarChart3, Activity } from 'lucide-react';
import { Link } from '@/i18n/navigation';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { RunCampaignDialog } from '../run-campaign-dialog';
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
import { DeviceStepsPanel } from '@/features/devices/components/device-step-monitor';
import { List } from 'lucide-react';
import { AddDevicesToCampaignDialog } from '../add-devices-dialog';
import { ScenarioListDialog } from '../scenario-list-dialog';
import { CampaignMonitorDialog } from '../campaign-monitor';
import { ROUTES } from '@/config/routes';
import { CampaignRunProgress } from './CampaignRunProgress';
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
import { isCampaignActiveExecution, isIdleStatus } from '../../types';

export function CampaignRowActions({ campaign }: { campaign: CampaignOut }) {
  const t = useTranslations('campaignsFeature.list');
  const tAdd = useTranslations('campaignsFeature.addDevices');
  const tScenario = useTranslations('campaignsFeature.scenarioList');

  const [runDialogOpen, setRunDialogOpen] = useState(false);

  const { data: devices = [] } = useCampaignDevices(campaign.id);
  const { data: scenarios = [] } = useScenarios(campaign.id);

  const { mutate: patchCampaignStatus, isPending: isPatchingCampaign } =
    useUpdateCampaignStatus();
  const runMutation = useRunCampaign(
    () => toast.success(t('campaignDone')),
    { onTemporalFallback: () => toast.warning(t('temporalFallback')) }
  );
  const { mutate: runCampaign, isPending: isRunning } = runMutation;
  const { mutate: deleteCampaign, isPending: isDeleting } = useDeleteCampaign();

  const { data: wfData } = useCampaignWorkflows(
    campaign.id,
    isCampaignActiveExecution(campaign.status)
  );
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
    if (campaign.status === 'paused') {
      patchCampaignStatus(
        { id: campaign.id, status: 'running' },
        { onError: () => toast.error(t('runFailed')) }
      );
      toast.info(
        t('resumingAll', { count: Math.max(1, pausedWorkflowIds.length) })
      );
      return;
    }
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

  const running = isCampaignActiveExecution(campaign.status);
  const disabledRun = isPatchingCampaign || isRunning || devices.length === 0 || !hasScenario;
  const disabledRunReason = !hasScenario
    ? tScenario('emptyDescription')
    : devices.length === 0
      ? t('titleNeedDevice')
      : t('loading');

  return (
    <div
      className={
        running
          ? 'flex min-w-0 flex-col gap-2 rounded-lg border border-border/40 bg-muted/5 p-2.5'
          : 'flex min-w-0 flex-col gap-2'
      }
    >
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <div className='flex flex-wrap items-center gap-1.5'>
          <AddDevicesToCampaignDialog
            campaignId={campaign.id}
            campaignName={campaign.name}
            deviceCount={devices.length}
          >
            <Button size='sm' variant='outline' className='h-7 gap-1.5 px-2.5 text-[11px]'>
              <Smartphone size={13} />
              {devices.length}
            </Button>
          </AddDevicesToCampaignDialog>

          <ScenarioListDialog campaign={campaign}>
            <Button size='sm' variant='outline' className='h-7 gap-1.5 px-2.5 text-[11px]'>
              <FileText size={13} />
              {scenarios.length}
            </Button>
          </ScenarioListDialog>

          <Button size='sm' variant='ghost' className='h-7 gap-1.5 px-2 text-[11px]' asChild>
            <Link href={ROUTES.CONTENT.BY_CAMPAIGN(campaign.id)}>
              <BarChart3 size={13} />
            </Link>
          </Button>
        </div>

        <div className='flex flex-wrap items-center gap-1.5'>
          {isIdleStatus(campaign.status) && (
            <>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size='sm'
                    variant='default'
                    className='h-7 gap-1.5 px-2.5 text-[11px]'
                    disabled={disabledRun}
                    onClick={() => setRunDialogOpen(true)}
                  >
                    <Play size={13} />
                    {t('titleRun')}
                  </Button>
                </TooltipTrigger>
                {disabledRun && (
                  <TooltipContent side='top' className='text-xs'>
                    {disabledRunReason}
                  </TooltipContent>
                )}
              </Tooltip>

              <RunCampaignDialog
                open={runDialogOpen}
                onClose={() => setRunDialogOpen(false)}
                devices={devices}
                isRunning={isRunning}
                onConfirm={(deviceSerials) => {
                  setRunDialogOpen(false);
                  runCampaign({ id: campaign.id, deviceSerials }, {
                    onError: (err: unknown) => {
                      const msg =
                        err && typeof err === 'object' && 'response' in err
                          ? (err as { response?: { data?: { error?: string } } }).response?.data?.error
                          : null;
                      toast.error(msg ?? t('runFailed'));
                    },
                  });
                }}
              />
            </>
          )}

          {running && runningWorkflowIds.length > 0 && (
            <Button
              size='sm'
              variant='outline'
              className='h-7 gap-1.5 px-2.5 text-[11px]'
              disabled={isPausing}
              onClick={handlePauseAll}
            >
              <Pause size={13} />
              {t('titlePause')}
            </Button>
          )}
          {running && pausedWorkflowIds.length > 0 && (
            <Button
              size='sm'
              variant='outline'
              className='h-7 gap-1.5 px-2.5 text-[11px] text-green-600 hover:text-green-600'
              disabled={isResuming || isPatchingCampaign}
              onClick={handleResumeAll}
            >
              <Play size={13} />
              {t('titleResume')}
            </Button>
          )}
          {running && hasActiveWorkflows && (
            <Button
              size='sm'
              variant='ghost'
              className='h-7 gap-1 px-2 text-[11px] text-destructive hover:text-destructive'
              disabled={isCancelling}
              onClick={handleCancelAll}
            >
              <Square size={13} />
            </Button>
          )}
          {running && previewSerial && (
            <Dialog>
              <DialogTrigger asChild>
                <Button size='sm' variant='ghost' className='h-7 gap-1.5 px-2 text-[11px]'>
                  <Eye size={13} />
                  Live
                </Button>
              </DialogTrigger>
              <DialogContent className='w-[90vw] sm:max-w-[1200px] max-h-[90vh] overflow-hidden flex flex-col'>
                <DialogHeader className='shrink-0'>
                  <DialogTitle className='text-sm'>{t('liveDialogTitle')}</DialogTitle>
                </DialogHeader>
                <div className='flex min-h-0 flex-1 divide-x overflow-hidden'>
                  <div className='w-[380px] shrink-0 overflow-y-auto pr-3'>
                    <DeviceControlEmbed initialSerial={previewSerial} compact hideStepMonitor />
                  </div>
                  <div className='flex min-w-0 flex-1 flex-col pl-3'>
                    <p className='mb-2 shrink-0 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
                      <List size={10} /> Các bước
                    </p>
                    <div className='flex-1 overflow-y-auto'>
                      <DeviceStepsPanel serial={previewSerial} />
                    </div>
                  </div>
                </div>
              </DialogContent>
            </Dialog>
          )}
          <CampaignMonitorDialog campaign={campaign}>
            <Button size='sm' variant='ghost' className='h-7 gap-1.5 px-2 text-[11px]'>
              <Activity size={13} />
              {t('titleMonitor')}
            </Button>
          </CampaignMonitorDialog>

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
      </div>

      <CampaignRunProgress campaignId={campaign.id} isRunning={running} />
    </div>
  );
}
