'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Play,
  Pause,
  Square,
  Trash2,
  MoreHorizontal,
  Smartphone,
  FileText,
  BarChart3,
  MonitorPlay
} from 'lucide-react';
import { Link } from '@/i18n/navigation';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { RunCampaignDialog } from '../run-campaign-dialog';
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
import { AddDevicesToCampaignDialog } from '../add-devices-dialog';
import { ScenarioListDialog } from '../scenario-list-dialog';
import { CampaignMonitorDialog } from '../campaign-monitor';
import { ROUTES } from '@/config/routes';
import { cn } from '@/lib/utils';
import { CampaignRunProgress } from './CampaignRunProgress';
import {
  useCampaignDevices,
  useCampaignWorkflows,
  useDeleteCampaign,
  useRunCampaign,
  useScenarios,
  useUpdateCampaignStatus,
  useWorkflowPause,
  useWorkflowResume,
  useWorkflowCancel,
} from '../../hooks/use-campaigns';
import type { CampaignOut } from '../../types';
import { isCampaignActiveExecution, isIdleStatus } from '../../types';
import { useConfirm } from '@/providers/modal-provider';

export function CampaignRowActions({ campaign }: { campaign: CampaignOut }) {
  const t = useTranslations('campaignsFeature.list');
  const tCommon = useTranslations('common');
  const confirm = useConfirm();
  const tAdd = useTranslations('campaignsFeature.addDevices');
  const tScenario = useTranslations('campaignsFeature.scenarioList');
  const router = useRouter();

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
  const pausedWorkflowIds = workflows.filter((w) => w.status === 'PAUSED' || w.status === 'paused_on_error').map((w) => w.workflow_id);
  const activeWorkflowIds = [...runningWorkflowIds, ...pausedWorkflowIds];
  const hasActiveWorkflows = activeWorkflowIds.length > 0;

  const { mutate: pauseWf, isPending: isPausing } = useWorkflowPause();
  const { mutate: resumeWf, isPending: isResuming } = useWorkflowResume();
  const { mutateAsync: cancelWf, isPending: isCancelling } = useWorkflowCancel();

  const previewSerial = devices[0]?.serial ?? '';
  const totalSteps = scenarios.reduce((s, sc) => s + sc.steps.length, 0);
  const hasScenario = totalSteps > 0;

  const handleDelete = () => {
    void (async () => {
      const ok = await confirm({
        title: t('titleDelete'),
        description: t('deleteConfirm'),
        confirmText: tCommon('confirm'),
        cancelText: tCommon('cancel'),
        confirmVariant: 'destructive',
        zIndex: 10_000
      });
      if (!ok) return;
      deleteCampaign(campaign.id, {
        onSuccess: () => toast.success(t('deleteSuccess')),
        onError: () => toast.error(t('deleteFailed')),
      });
    })();
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

  const handleCancelAll = async () => {
    const ok = await confirm({
      title: t('titleCancelAll'),
      description: t('cancelConfirm'),
      confirmText: tCommon('confirm'),
      cancelText: tCommon('cancel'),
      confirmVariant: 'destructive',
      zIndex: 10000,
    });
    if (!ok) return;
    const results = await Promise.allSettled(
      activeWorkflowIds.map((id) => cancelWf(id))
    );
    const failed = results.filter((r) => r.status === 'rejected').length;
    if (failed > 0) {
      toast.error(`Cancel failed for ${failed} workflow(s)`);
      return;
    }
    patchCampaignStatus(
      { id: campaign.id, status: 'idle' },
      {
        onError: () => toast.error(t('runFailed')),
      },
    );
    toast.info(t('cancellingAll', { count: activeWorkflowIds.length }));
  };

  const running = isCampaignActiveExecution(campaign.status);
  const disabledRun = isPatchingCampaign || isRunning || devices.length === 0 || !hasScenario;
  const disabledRunReason = !hasScenario
    ? tScenario('emptyDescription')
    : devices.length === 0
      ? t('titleNeedDevice')
      : t('loading');

  return (
    <div className='flex min-w-0 items-center justify-end'>
      <div className='flex flex-wrap items-center justify-end gap-1.5'>
        <div className='flex items-center gap-1.5'>
          <AddDevicesToCampaignDialog
            campaignId={campaign.id}
            campaignName={campaign.name}
            deviceCount={devices.length}
          >
            <Button
              size='sm'
              variant='outline'
              className='h-8 gap-1.5 px-2.5 text-xs'
              title={`${devices.length} thiết bị`}
            >
              <Smartphone size={13} />
              {devices.length}
            </Button>
          </AddDevicesToCampaignDialog>

          <ScenarioListDialog campaign={campaign}>
            <Button
              size='sm'
              variant='outline'
              className='h-8 gap-1.5 px-2.5 text-xs'
              title={`${scenarios.length} kịch bản`}
            >
              <FileText size={13} />
              {scenarios.length}
            </Button>
          </ScenarioListDialog>

          <Button
            size='sm'
            variant='ghost'
            className='h-8 w-8 p-0'
            asChild
            title='Xem dữ liệu thu thập'
          >
            <Link href={ROUTES.CONTENT.BY_CAMPAIGN(campaign.id)} aria-label='Xem dữ liệu thu thập'>
              <BarChart3 size={14} />
            </Link>
          </Button>
        </div>

        <span className='mx-1 h-5 w-px bg-border' aria-hidden='true' />

        <div className='flex items-center gap-1.5'>
          <CampaignRunProgress campaignId={campaign.id} isRunning={running} />

          {isIdleStatus(campaign.status) && (
            <>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size='sm'
                    variant='default'
                    className='h-8 gap-1.5 px-3 text-xs font-semibold'
                    disabled={disabledRun}
                    onClick={() => setRunDialogOpen(true)}
                  >
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
                campaignId={campaign.id}
                campaignVariables={campaign.variables ?? {}}
                onClose={() => setRunDialogOpen(false)}
                devices={devices}
                scenarios={scenarios}
                isRunning={isRunning}
                onConfirm={(deviceSerials) => {
                  setRunDialogOpen(false);
                  runCampaign({ id: campaign.id, deviceSerials }, {
                    onSuccess: () => {
                      const count = deviceSerials?.length ?? devices.length;
                      toast.success(
                        t('runStarted', { count }),
                        { description: campaign.name, duration: 4000 }
                      );
                      router.push(ROUTES.DEVICES.ROOT);
                    },
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
              className='h-8 gap-1.5 px-3 text-xs'
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
              className='h-8 gap-1.5 px-3 text-xs text-green-600 hover:text-green-600'
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
              className='h-8 w-8 p-0 text-destructive hover:text-destructive'
              disabled={isPatchingCampaign || isCancelling}
              onClick={handleCancelAll}
              title={t('titleCancel') ?? 'Huỷ'}
              aria-label='Huỷ'
            >
              <Square size={13} />
            </Button>
          )}
          {/* {running && previewSerial && (
            <Dialog>
              <DialogTrigger asChild>
                <Button size='sm' variant='ghost' className='h-8 gap-1.5 px-2 text-xs'>
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
                      <List size={10} /> {t('monitorStepsHeading')}
                    </p>
                    <div className='flex-1 overflow-y-auto'>
                      <DeviceStepsPanel serial={previewSerial} />
                    </div>
                  </div>
                </div>
              </DialogContent>
            </Dialog>
          )} */}
          <CampaignMonitorDialog campaign={campaign}>
            <Button
              type='button'
              size='sm'
              variant='secondary'
              className={cn(
                'h-8 gap-2 border px-2.5 text-xs shadow-sm transition-colors duration-200',
                'cursor-pointer hover:border-primary/30 hover:bg-primary/[0.06]',
                running && 'border-primary/25 bg-primary/[0.07] text-primary'
              )}
            >
              <span className='relative flex size-4 shrink-0 items-center justify-center'>
                <MonitorPlay size={14} className='shrink-0' strokeWidth={2} aria-hidden />
                {running && (
                  <span
                    className='absolute -right-0.5 -top-0.5 size-1.5 rounded-full bg-emerald-500 ring-2 ring-background'
                    aria-hidden
                  />
                )}
              </span>
              {t('titleMonitor')}
            </Button>
          </CampaignMonitorDialog>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size='sm'
                variant='ghost'
                className='h-8 w-8 p-0'
                aria-label='Thêm hành động'
              >
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
    </div>
  );
}
