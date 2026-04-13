'use client';

import { useState } from 'react';
import { Play, Pause, Square, Trash2, Eye, MoreHorizontal, Smartphone, FileText, BarChart3 } from 'lucide-react';
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

  return (
    <div
      className={
        running
          ? 'flex min-w-0 flex-col gap-2 rounded-lg border border-border/40 bg-muted/5 p-2'
          : 'flex min-w-0 flex-col'
      }
    >
      <div className='flex flex-wrap items-center gap-1'>

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

        {/* ── Kết quả ── */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button size='sm' variant='ghost' className='h-7 gap-1.5 px-2 text-xs' asChild>
              <Link href={ROUTES.CONTENT.BY_CAMPAIGN(campaign.id)}>
                <BarChart3 size={13} />
              </Link>
            </Button>
          </TooltipTrigger>
          <TooltipContent side='top' className='text-xs'>Xem kết quả thu thập</TooltipContent>
        </Tooltip>

        <div className='mx-1 h-4 w-px bg-border' />

        {/* ── Run ── */}
        {isIdleStatus(campaign.status) && (
          <>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size='sm'
                  variant={hasScenario ? 'default' : 'outline'}
                  className='h-7 gap-1.5 px-2.5 text-xs'
                  disabled={isPatchingCampaign || isRunning}
                  onClick={() => setRunDialogOpen(true)}
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

        {/* ── Running controls ── */}
        {running && (
          <>
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
                disabled={isResuming || isPatchingCampaign}
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
            {previewSerial && (
              <Dialog>
                <DialogTrigger asChild>
                  <Button size='sm' variant='ghost' className='h-7 gap-1.5 px-2 text-xs'>
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

      <CampaignRunProgress campaignId={campaign.id} isRunning={running} />
    </div>
  );
}
