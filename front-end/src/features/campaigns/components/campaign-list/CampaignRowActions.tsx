'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  Play,
  Pause,
  Square,
  Trash2,
  MoreHorizontal,
  BarChart3,
  History,
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
import { CampaignRunHistoryDialog } from '../campaign-run-history-dialog';
import { ROUTES } from '@/config/routes';
import { cn } from '@/lib/utils';
import {
  useCampaignDevices,
  useCampaignWorkflows,
  useCampaign,
  useCampaignCancel,
  useCampaignPause,
  useCampaignResume,
  useCampaignStopDrain,
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
import { summarizeDispatchResult } from '../../lib/campaign-dispatch-result';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import {
  automationPrimaryAction,
  automationRunState,
  campaignRunJourney,
  shouldResumeAutomationReview
} from '../../lib/automation-start';
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
  const searchParams = useSearchParams();
  const linkedRunHistory =
    searchParams.get('campaign_id') === campaign.id &&
    searchParams.get('panel') === 'run-log';
  const linkedExecutionId = linkedRunHistory
    ? searchParams.get('execution_id')
    : null;

  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [dispatchDialogOpen, setDispatchDialogOpen] = useState(false);
  const [automationDialogOpen, setAutomationDialogOpen] = useState(false);
  const [runHistoryOpen, setRunHistoryOpen] = useState(linkedRunHistory);
  const [resumeAutomationReview, setResumeAutomationReview] = useState(false);
  const [addDevicesOpen, setAddDevicesOpen] = useState(false);
  const [scenarioOpen, setScenarioOpen] = useState(false);
  const [entityEditOpen, setEntityEditOpen] = useState(false);

  useEffect(() => {
    if (linkedRunHistory) setRunHistoryOpen(true);
  }, [linkedRunHistory]);

  const detailNeeded =
    runDialogOpen ||
    dispatchDialogOpen ||
    automationDialogOpen ||
    scenarioOpen ||
    entityEditOpen;

  const { data: campaignDetail, isFetching: detailFetching } = useCampaign(
    campaign.id,
    detailNeeded
  );
  const effectiveCampaign = campaignDetail ?? campaign;
  const isEntityCampaign =
    isCampaignEntityOut(effectiveCampaign) ||
    (campaignDetail != null && isCampaignEntityOut(campaignDetail));
  const entityDetail: CampaignEntityOut | null = (() => {
    const row = effectiveCampaign;
    return isCampaignEntityOut(row) ? row : null;
  })();
  const effectiveVariables = campaignVariables(effectiveCampaign);
  const runJourney = campaignRunJourney(isEntityCampaign, false);
  const automationAction = automationPrimaryAction(
    automationRunState(effectiveVariables)
  );
  const scenarioRefIds = useMemo(
    () => (entityDetail?.scenario_refs ?? []).map((ref) => ref.scenario_id),
    [entityDetail?.scenario_refs]
  );
  const { data: orgScenarios = [] } = useOrgScenarios({
    enabled: (dispatchDialogOpen || automationDialogOpen) && isEntityCampaign
  });
  const orgScenarioBodies = useOrgScenarioBodies(
    scenarioRefIds,
    (dispatchDialogOpen || automationDialogOpen) && isEntityCampaign
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
        const steps =
          bodyJson && typeof bodyJson === 'object'
            ? ((bodyJson as Record<string, unknown>).steps as
                | unknown[]
                | undefined)
            : undefined;
        const requirements =
          bodyJson && typeof bodyJson === 'object'
            ? ((bodyJson as Record<string, unknown>).requirements as
                | Record<string, unknown>
                | undefined)
            : undefined;
        return {
          id,
          name: orgScenarios.find((row) => row.id === id)?.name ?? id,
          variables,
          steps,
          requirements
        };
      }),
    [orgScenarioBodies, orgScenarios, scenarioRefIds]
  );

  const { data: fetchedDevices } = useCampaignDevices(
    campaign.id,
    runDialogOpen ||
      dispatchDialogOpen ||
      automationDialogOpen ||
      addDevicesOpen
  );
  const { data: fetchedScenarios } = useScenarios(
    campaign.id,
    runDialogOpen || scenarioOpen
  );
  const devices = fetchedDevices ?? campaign.devices ?? [];
  const scenarios = fetchedScenarios ?? campaign.scenarios ?? [];
  const deviceAssignmentsKnown =
    fetchedDevices !== undefined || Array.isArray(campaign.devices);
  const { data: executionRuntime } = useExecutionRuntime();

  const runMutation = useRunCampaign(() => toast.success(t('campaignDone')), {
    onTemporalFallback: () => toast.warning(t('temporalFallback'))
  });
  const dispatchMutation = useDispatchCampaign((summary) => {
    if (!summary?.allFailed) toast.success(t('campaignDone'));
  });
  const { mutate: runCampaign, isPending: isRunning } = runMutation;
  const { mutate: dispatchCampaign, isPending: isDispatching } =
    dispatchMutation;
  const isStarting = isRunning || isDispatching;
  const { mutate: deleteCampaign, isPending: isDeleting } = useDeleteCampaign();

  const { isStopping, activeWorkflowCount, activeExecutionCount } =
    useCampaignStopDrain(campaign.id, campaign.status);

  const { data: wfData } = useCampaignWorkflows(
    campaign.id,
    isCampaignActiveExecution(campaign.status) || isStopping
  );
  const workflows = wfData?.workflows ?? [];
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
      if (deviceAssignmentsKnown && devices.length === 0 && !isEntityCampaign) {
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
      : (!deviceAssignmentsKnown || devices.length > 0) && hasScenario;
    if (runJourney === 'automation' && automationAction !== 'setup') {
      return {
        label: t(`automationActions.${automationAction}`),
        onClick: () => router.push(ROUTES.CAMPAIGNS.MONITOR(campaign.id)),
        disabled: !perms.canExecute
      };
    }
    return {
      label:
        runJourney === 'automation'
          ? t('automationActions.setup')
          : t('titleRun'),
      onClick: () =>
        runJourney === 'automation'
          ? (() => {
              setResumeAutomationReview(false);
              setAutomationDialogOpen(true);
            })()
          : runJourney === 'dispatch'
            ? setDispatchDialogOpen(true)
            : setRunDialogOpen(true),
      disabled: !canRun || !perms.canExecute,
      tooltip: !hasScenario
        ? t('missingScenario')
        : !isEntityCampaign && deviceAssignmentsKnown && devices.length === 0
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
      if ((data.workflows_signalled ?? 0) > 0) {
        toast.info(
          t('cancellingAll', { count: data.workflows_signalled ?? 0 })
        );
      }
    } catch (err) {
      toast.error(formatFarmApiError(err, t('cancelFailed')));
    }
  };

  const running = isCampaignActiveExecution(campaign.status) || isStopping;
  // Pause reads the campaign's own status, the same source Stop already trusts.
  // It used to require the workflow listing to name a running row, which asks
  // the wrong question in three ways: the listing lags its 12s poll, it is
  // keyed on ID shapes that a continuous crawl and a fan-out dispatch do not
  // use, and it is empty for a beat after a run starts. Every one of those made
  // pause vanish from a campaign that was plainly running — while the badge
  // beside it read "running" off the very status checked here.
  const showPause = campaign.status === 'running';
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
              campaignVariables={effectiveCampaign.variables ?? {}}
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
                        const summary = summarizeDispatchResult(data);
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
                        if (summary.allFailed) {
                          toast.error(
                            summary.allFailuresAreDeviceClaim
                              ? t('dispatchAllDevicesBusy', {
                                  count: summary.deviceClaimFailed
                                })
                              : t('dispatchAllFailed', {
                                  count: summary.failed
                                }),
                            {
                              description: campaign.name,
                              duration: 8000
                            }
                          );
                          return;
                        }
                        toast.success(
                          t('dispatchStarted', { count: data.target_count }),
                          {
                            description:
                              summary.failed > 0
                                ? t('dispatchPartialFailures', {
                                    count: summary.failed
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
            disabled={isCancelling || isStopping}
            onClick={handleCancelAll}
            title={isStopping ? t('statusStopping') : t('titleCancel')}
            aria-label={isStopping ? t('statusStopping') : t('titleCancel')}
          >
            <Square size={13} />
          </Button>
        )}
        {isStopping ? (
          <span
            className='hidden max-w-[8rem] truncate text-[10px] text-amber-700 dark:text-amber-300 xl:inline'
            title={t('stoppingDetail', {
              workflows: activeWorkflowCount,
              executions: activeExecutionCount
            })}
          >
            {t('statusStopping')}
          </span>
        ) : null}

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
              <DropdownMenuItem
                className='gap-2'
                onClick={() => setRunHistoryOpen(true)}
              >
                <History size={14} />
                {t('titleRunHistory')}
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
        onOpenChange={(open) => {
          setAddDevicesOpen(open);
          if (shouldResumeAutomationReview(open, resumeAutomationReview)) {
            setAutomationDialogOpen(true);
          }
        }}
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
        campaign={effectiveCampaign}
        open={entityEditOpen}
        onOpenChange={(open) => {
          setEntityEditOpen(open);
          if (shouldResumeAutomationReview(open, resumeAutomationReview)) {
            setAutomationDialogOpen(true);
          }
        }}
      />
      <CampaignRunHistoryDialog
        campaign={campaign}
        open={runHistoryOpen}
        onOpenChange={setRunHistoryOpen}
        initialExecutionId={linkedExecutionId}
      />
    </div>
  );
}
