'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Play,
  Pause,
  Square,
  Trash2,
  MoreHorizontal,
  BarChart3,
  MonitorPlay,
  Pencil
} from 'lucide-react';
import { Link } from '@/i18n/navigation';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { RunCampaignDialog } from '../run-campaign-dialog';
import { DispatchCampaignDialog } from '../dispatch-campaign-dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { AddDevicesToCampaignDialog } from '../add-devices-dialog';
import { ScenarioListDialog } from '../scenario-list-dialog';
import { EditCampaignEntityDialog } from '../edit-campaign-entity-dialog';
import { CampaignMonitorDialog } from '../campaign-monitor';
import { ROUTES } from '@/config/routes';
import { cn } from '@/lib/utils';
import { CampaignRunProgress } from './CampaignRunProgress';
import {
  useCampaignDevices,
  useCampaignWorkflows,
  useCampaign,
  useCampaignCancel,
  useCampaignPause,
  useCampaignResume,
  useDeleteCampaign,
  useDispatchCampaign,
  useExecutionRuntime,
  useRunCampaign,
  useScenarios
} from '../../hooks/use-campaigns';
import type { CampaignOut } from '../../types';
import {
  campaignVariables,
  isCampaignEntityOut,
  type CampaignEntityOut
} from '../../services/api';
import { useOrgScenarioBodies } from '@/features/org-scenarios/hooks/use-org-scenarios';
import { useOrgScenarios } from '@/features/org-scenarios/hooks/use-org-scenarios';
import {
  isCampaignActiveExecution,
  isCampaignMetadataEditable,
  isDispatchableStatus
} from '../../types';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { useConfirm } from '@/providers/modal-provider';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';

export function CampaignRowActions({
  campaign,
  layout = 'inline'
}: {
  campaign: CampaignOut;
  layout?: 'inline' | 'stacked';
}) {
  const t = useTranslations('campaignsFeature.list');
  const tCommon = useTranslations('common');
  const confirm = useConfirm();
  const perms = useResourcePermissions('campaigns');
  const router = useRouter();

  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [dispatchDialogOpen, setDispatchDialogOpen] = useState(false);
  const [addDevicesOpen, setAddDevicesOpen] = useState(false);
  const [scenarioOpen, setScenarioOpen] = useState(false);
  const [entityEditOpen, setEntityEditOpen] = useState(false);

  const { data: campaignDetail, isFetching: detailFetching } = useCampaign(
    campaign.id,
    perms.canExecute || perms.canUpdate
  );
  const isEntityCampaign =
    isCampaignEntityOut(campaign) ||
    (campaignDetail != null && isCampaignEntityOut(campaignDetail));
  const entityDetail: CampaignEntityOut | null = (() => {
    const row = campaignDetail ?? campaign;
    return isCampaignEntityOut(row) ? row : null;
  })();
  const scenarioRefIds = useMemo(
    () => (entityDetail?.scenario_refs ?? []).map((ref) => ref.scenario_id),
    [entityDetail?.scenario_refs]
  );
  const { data: orgScenarios = [] } = useOrgScenarios();
  const orgScenarioBodies = useOrgScenarioBodies(
    scenarioRefIds,
    dispatchDialogOpen && isEntityCampaign
  );
  const dispatchScenarios = useMemo(
    () =>
      scenarioRefIds.map((id, index) => {
        const bodyJson = orgScenarioBodies[index]?.data?.body_json;
        const variables =
          bodyJson && typeof bodyJson === 'object'
            ? ((bodyJson as Record<string, unknown>).variables as
                | Record<string, unknown>
                | undefined)
            : undefined;
        return {
          id,
          name: orgScenarios.find((row) => row.id === id)?.name ?? id,
          variables
        };
      }),
    [orgScenarioBodies, orgScenarios, scenarioRefIds]
  );

  const { data: devices = [] } = useCampaignDevices(campaign.id);
  const { data: scenarios = [] } = useScenarios(campaign.id);
  const { data: executionRuntime } = useExecutionRuntime();

  const runMutation = useRunCampaign(() => toast.success(t('campaignDone')), {
    onTemporalFallback: () => toast.warning(t('temporalFallback'))
  });
  const dispatchMutation = useDispatchCampaign(() =>
    toast.success(t('campaignDone'))
  );
  const { mutate: runCampaign, isPending: isRunning } = runMutation;
  const { mutate: dispatchCampaign, isPending: isDispatching } =
    dispatchMutation;
  const isStarting = isRunning || isDispatching;
  const { mutate: deleteCampaign, isPending: isDeleting } = useDeleteCampaign();

  const { data: wfData } = useCampaignWorkflows(
    campaign.id,
    isCampaignActiveExecution(campaign.status)
  );
  const workflows = wfData?.workflows ?? [];
  const hasActiveWorkflows = workflows.some(
    (w) =>
      w.status === 'RUNNING' ||
      w.status === 'PAUSED' ||
      w.status === 'paused_on_error'
  );
  const runningWorkflowIds = workflows
    .filter((w) => w.status === 'RUNNING')
    .map((w) => w.workflow_id);
  const pausedWorkflowIds = workflows
    .filter((w) => w.status === 'PAUSED' || w.status === 'paused_on_error')
    .map((w) => w.workflow_id);

  const { mutate: pauseCampaign, isPending: isPausing } = useCampaignPause();
  const { mutate: resumeCampaign, isPending: isResuming } = useCampaignResume();
  const { mutateAsync: cancelCampaign, isPending: isCancelling } =
    useCampaignCancel();

  const totalSteps = scenarios.reduce((s, sc) => s + sc.steps.length, 0);
  const entityRefCount = isEntityCampaign
    ? (entityDetail?.scenario_refs?.length ?? 0)
    : 0;
  const hasScenario = totalSteps > 0 || entityRefCount > 0;
  const canDispatch = isDispatchableStatus(campaign.status);
  const canEditEntity = isCampaignMetadataEditable(campaign.status);

  type PrimaryAction = {
    label: string;
    onClick: () => void;
    disabled: boolean;
    tooltip?: string;
  };

  const primaryAction: PrimaryAction = (() => {
    if (isStarting || (perms.canExecute && detailFetching && !campaignDetail)) {
      return {
        label: t('titleRun'),
        onClick: () => {},
        disabled: true,
        tooltip: t('loading')
      };
    }

    if (layout === 'stacked') {
      if (!hasScenario) {
        return {
          label: t('titleAddScenario'),
          onClick: () => setScenarioOpen(true),
          disabled: !perms.canUpdate,
          tooltip: t('missingScenario')
        };
      }
      if (devices.length === 0 && !isEntityCampaign) {
        return {
          label: t('titleNeedDevice'),
          onClick: () => setAddDevicesOpen(true),
          disabled: !perms.canUpdate,
          tooltip: t('titleNeedDevice')
        };
      }
    }

    const canRun = isEntityCampaign
      ? hasScenario
      : devices.length > 0 && hasScenario;
    return {
      label: t('titleRun'),
      onClick: () =>
        isEntityCampaign ? setDispatchDialogOpen(true) : setRunDialogOpen(true),
      disabled: !canRun || !perms.canExecute,
      tooltip: !hasScenario
        ? t('missingScenario')
        : !isEntityCampaign && devices.length === 0
          ? t('titleNeedDevice')
          : undefined
    };
  })();

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
        onError: (err) =>
          toast.error(formatFarmApiError(err, t('deleteFailed')))
      });
    })();
  };

  const handlePauseAll = () => {
    pauseCampaign(campaign.id, {
      onSuccess: (data) => {
        toast.info(t('pausingAll', { count: data.workflows_signalled ?? 0 }));
      },
      onError: () => toast.error(t('runFailed'))
    });
  };

  const handleResumeAll = () => {
    resumeCampaign(campaign.id, {
      onSuccess: () => {
        toast.info(
          t('resumingAll', {
            count:
              workflows.filter(
                (w) => w.status === 'PAUSED' || w.status === 'paused_on_error'
              ).length || 1
          })
        );
      },
      onError: () => toast.error(t('runFailed'))
    });
  };

  const handleCancelAll = async () => {
    const ok = await confirm({
      title: t('titleCancelAll'),
      description: `${t('cancelConfirm')}\n\n${t('cancelUndoWarning')}`,
      confirmText: tCommon('confirm'),
      cancelText: tCommon('cancel'),
      confirmVariant: 'destructive',
      zIndex: 10000
    });
    if (!ok) return;
    try {
      const data = await cancelCampaign({ campaignId: campaign.id });
      toast.success(t('cancelSuccess'));
      toast.info(t('cancellingAll', { count: data.workflows_signalled ?? 0 }));
    } catch (err) {
      toast.error(formatFarmApiError(err, t('cancelFailed')));
    }
  };

  const running = isCampaignActiveExecution(campaign.status);
  const showPause =
    campaign.status === 'running' &&
    (hasActiveWorkflows || runningWorkflowIds.length > 0);
  const showResume =
    campaign.status === 'paused' || pausedWorkflowIds.length > 0;

  return (
    <div
      className={cn(
        'flex min-w-0',
        layout === 'stacked'
          ? 'w-full flex-col gap-2'
          : 'items-center justify-end'
      )}
    >
      <div
        className={cn(
          'flex shrink-0 items-center gap-1.5',
          layout === 'stacked' ? 'w-full flex-wrap' : 'flex-nowrap'
        )}
      >
        <CampaignRunProgress campaignId={campaign.id} isRunning={running} />

        {canDispatch && perms.canExecute && (
          <>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size='sm'
                  variant='default'
                  className='h-8 shrink-0 gap-1.5 px-3 text-xs font-semibold'
                  disabled={primaryAction.disabled}
                  onClick={primaryAction.onClick}
                >
                  {primaryAction.label}
                </Button>
              </TooltipTrigger>
              {primaryAction.disabled && primaryAction.tooltip ? (
                <TooltipContent side='top' className='text-xs'>
                  {primaryAction.tooltip}
                </TooltipContent>
              ) : null}
            </Tooltip>

            <RunCampaignDialog
              open={runDialogOpen && !isEntityCampaign}
              campaignId={campaign.id}
              campaignVariables={campaign.variables ?? {}}
              onClose={() => setRunDialogOpen(false)}
              devices={devices}
              scenarios={scenarios}
              isRunning={isRunning}
              onConfirm={(deviceSerials) => {
                setRunDialogOpen(false);
                runCampaign(
                  { id: campaign.id, deviceSerials },
                  {
                    onSuccess: () => {
                      const count = deviceSerials?.length ?? devices.length;
                      toast.success(t('runStarted', { count }), {
                        description: campaign.name,
                        duration: 4000
                      });
                      router.push(ROUTES.DEVICES.ROOT);
                    },
                    onError: (err: unknown) => {
                      toast.error(formatFarmApiError(err, t('runFailed')));
                    }
                  }
                );
              }}
            />

            {isEntityCampaign ? (
              <DispatchCampaignDialog
                open={dispatchDialogOpen}
                campaignId={campaign.id}
                onClose={() => setDispatchDialogOpen(false)}
                devices={devices}
                scenarios={dispatchScenarios}
                campaignVariables={
                  entityDetail ? campaignVariables(entityDetail) : {}
                }
                perDeviceOverrides={entityDetail?.per_device_overrides ?? {}}
                isDispatching={isDispatching}
                onConfirm={(body) => {
                  setDispatchDialogOpen(false);
                  dispatchCampaign(
                    { id: campaign.id, body },
                    {
                      onSuccess: (data) => {
                        const failed =
                          data.executions?.filter(
                            (e) => e.status === 'failed' || e.failure_reason
                          ).length ?? 0;
                        const usedFallback =
                          executionRuntime?.campaign_run
                            ?.fallback_mode_active ||
                          data.executions?.some(
                            (e) => e.dispatch_source === 'fallback'
                          );
                        if (usedFallback) {
                          toast.warning(t('fallbackDispatchActive'), {
                            duration: 8000
                          });
                        }
                        toast.success(
                          t('dispatchStarted', { count: data.target_count }),
                          {
                            description:
                              failed > 0
                                ? t('dispatchPartialFailures', {
                                    count: failed
                                  })
                                : campaign.name,
                            duration: 5000
                          }
                        );
                        router.push(ROUTES.DEVICES.ROOT);
                      },
                      onError: (err) => {
                        toast.error(
                          formatFarmApiError(err, t('dispatchFailed'))
                        );
                      }
                    }
                  );
                }}
              />
            ) : null}
          </>
        )}

        {showPause && perms.canExecute && (
          <Button
            size='sm'
            variant='outline'
            className='h-8 shrink-0 gap-1.5 px-2.5 text-xs'
            disabled={isPausing}
            onClick={handlePauseAll}
          >
            <Pause size={13} />
            <span className='hidden xl:inline'>{t('titlePause')}</span>
          </Button>
        )}
        {showResume && perms.canExecute && (
          <Button
            size='sm'
            variant='outline'
            className='h-8 shrink-0 gap-1.5 px-2.5 text-xs text-green-600 hover:text-green-600'
            disabled={isResuming}
            onClick={handleResumeAll}
          >
            <Play size={13} />
            <span className='hidden xl:inline'>{t('titleResume')}</span>
          </Button>
        )}
        {running && perms.canExecute && (
          <Button
            size='sm'
            variant='ghost'
            className='h-8 w-8 p-0 text-destructive hover:text-destructive'
            disabled={isCancelling}
            onClick={handleCancelAll}
            title={t('titleCancel')}
            aria-label={t('titleCancel')}
          >
            <Square size={13} />
          </Button>
        )}

        <CampaignMonitorDialog campaign={campaign}>
          <Button
            type='button'
            size='sm'
            variant='secondary'
            className={cn(
              'h-8 shrink-0 gap-2 border px-2 text-xs shadow-sm transition-colors duration-200',
              layout === 'inline' && 'xl:px-2.5',
              'cursor-pointer hover:border-primary/30 hover:bg-primary/[0.06]',
              running && 'border-primary/25 bg-primary/[0.07] text-primary'
            )}
            title={t('titleMonitor')}
          >
            <span className='relative flex size-4 shrink-0 items-center justify-center'>
              <MonitorPlay
                size={14}
                className='shrink-0'
                strokeWidth={2}
                aria-hidden
              />
              {running && (
                <span
                  className='absolute -right-0.5 -top-0.5 size-1.5 rounded-full bg-emerald-500 ring-2 ring-background'
                  aria-hidden
                />
              )}
            </span>
            <span className='hidden xl:inline'>{t('titleMonitor')}</span>
          </Button>
        </CampaignMonitorDialog>

        {(perms.canUpdate || perms.canDelete) && (
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
            <DropdownMenuContent align='end' className='w-56'>
              <DropdownMenuItem asChild className='gap-2'>
                <Link href={ROUTES.CONTENT.BY_CAMPAIGN(campaign.id)}>
                  <BarChart3 size={14} />
                  {t('titleContent')}
                </Link>
              </DropdownMenuItem>

              {perms.canUpdate && isEntityCampaign ? (
                <DropdownMenuItem
                  className='gap-2'
                  disabled={!canEditEntity}
                  onClick={() => {
                    if (!canEditEntity) {
                      toast.error(t('editLocked'));
                      return;
                    }
                    setEntityEditOpen(true);
                  }}
                >
                  <Pencil size={14} />
                  {t('titleEditEntity')}
                </DropdownMenuItem>
              ) : null}

              {perms.canDelete ? (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className='gap-2 text-destructive focus:text-destructive'
                    disabled={
                      isDeleting || isCampaignActiveExecution(campaign.status)
                    }
                    onClick={handleDelete}
                  >
                    <Trash2 size={14} />
                    {t('titleDelete')}
                  </DropdownMenuItem>
                </>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      <AddDevicesToCampaignDialog
        campaignId={campaign.id}
        campaignName={campaign.name}
        deviceCount={devices.length}
        open={addDevicesOpen}
        onOpenChange={setAddDevicesOpen}
      >
        {null}
      </AddDevicesToCampaignDialog>

      <ScenarioListDialog
        campaign={campaign}
        open={scenarioOpen}
        onOpenChange={setScenarioOpen}
      >
        {null}
      </ScenarioListDialog>

      <EditCampaignEntityDialog
        campaign={campaign}
        open={entityEditOpen}
        onOpenChange={setEntityEditOpen}
      />
    </div>
  );
}
