'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  Play,
  Smartphone,
  CheckSquare,
  Square,
  Loader2,
  AlertCircle
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  DeviceVarsJsonPanel,
  formatDeviceVarsJson,
  mergeCampaignScenarioVariables,
  parseDeviceVarsJson
} from '@/components/device-vars-json-panel';
import { cn } from '@/lib/utils';
import { campaignsApi, scenarioDeviceCapabilitiesApi } from '../services/api';
import {
  scenarioCapabilityIssueSummary,
  scenarioCapabilityWarningSummary
} from '../lib/scenario-capability-preflight';
import {
  scenarioLintPreflightForSteps,
  scenarioLintSummary,
  type ScenarioLintPreflightResult
} from '../lib/scenario-lint-preflight';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import type { CampaignDeviceOut, ScenarioOut } from '../types';
import type { FlowStep } from './scenario-steps/types';
import { useConfirm } from '@/providers/modal-provider';

interface Props {
  open: boolean;
  campaignId: string;
  /** Campaign-level variables (merged with active scenario for read-only preview). */
  campaignVariables?: Record<string, unknown>;
  onClose: () => void;
  devices: CampaignDeviceOut[];
  scenarios: ScenarioOut[];
  isRunning: boolean;
  onConfirm: (deviceSerials?: string[]) => void;
}

const makePairKey = (scenarioId: string, deviceId: string) =>
  `${scenarioId}::${deviceId}`;

type CampaignCapabilityPreflightState = {
  ok: boolean;
  checked: number;
  issueSummary: string;
  warningSummary: string;
};

export function RunCampaignDialog({
  open,
  campaignId,
  campaignVariables = {},
  onClose,
  devices,
  scenarios,
  isRunning,
  onConfirm
}: Props) {
  const tList = useTranslations('campaignsFeature.list');
  const tVars = useTranslations('components.deviceVarsJson');
  const tModal = useTranslations('components.modal');
  const tCapabilityPreflight = useTranslations(
    'campaignsFeature.capabilityPreflight'
  );
  const tScenarioLintPreflight = useTranslations(
    'campaignsFeature.scenarioLintPreflight'
  );
  const confirm = useConfirm();
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [activeDeviceId, setActiveDeviceId] = useState<string>('');
  const [activeScenarioId, setActiveScenarioId] = useState<string>('');
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [deviceVarEnabled, setDeviceVarEnabled] = useState<
    Record<string, boolean>
  >({});
  const [dirtyKeys, setDirtyKeys] = useState<Record<string, true>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [isCapabilityChecking, setIsCapabilityChecking] = useState(false);
  const [capabilityPreflight, setCapabilityPreflight] =
    useState<CampaignCapabilityPreflightState | null>(null);

  const allSerials = useMemo(() => devices.map((d) => d.serial), [devices]);
  const deviceSignature = useMemo(
    () => devices.map((d) => d.id).join('|'),
    [devices]
  );
  const scenarioSignature = useMemo(
    () => scenarios.map((s) => s.id).join('|'),
    [scenarios]
  );
  const firstDeviceId = devices[0]?.id ?? '';
  const firstScenarioId = scenarios[0]?.id ?? '';
  const activeDevice = useMemo(
    () => devices.find((d) => d.id === activeDeviceId) ?? devices[0],
    [activeDeviceId, devices]
  );
  const activeScenario = useMemo(
    () => scenarios.find((s) => s.id === activeScenarioId) ?? scenarios[0],
    [activeScenarioId, scenarios]
  );
  const pairKey =
    activeScenarioId && activeDevice?.id
      ? makePairKey(activeScenarioId, activeDevice.id)
      : '';

  const campaignDetailQuery = useQuery({
    queryKey: ['campaigns', campaignId],
    queryFn: () => campaignsApi.get(campaignId),
    enabled: open && !!campaignId,
    staleTime: 0,
    refetchOnMount: 'always'
  });
  const effectiveCampaignVariables =
    campaignDetailQuery.data?.variables ?? campaignVariables;

  useEffect(() => {
    if (!open) return;
    setSelected(new Set(allSerials));
    setActiveDeviceId(firstDeviceId);
    setActiveScenarioId(firstScenarioId);
    setDrafts({});
    setDeviceVarEnabled({});
    setDirtyKeys({});
    setCapabilityPreflight(null);
  }, [
    allSerials,
    deviceSignature,
    firstDeviceId,
    firstScenarioId,
    open,
    scenarioSignature
  ]);

  const variableQuery = useQuery({
    queryKey: [
      'campaign-device-variables',
      campaignId,
      activeScenarioId,
      activeDevice?.id
    ],
    queryFn: () =>
      campaignsApi.getScenarioDeviceVariables(
        campaignId,
        activeScenarioId,
        activeDevice!.id
      ),
    enabled: open && !!campaignId && !!activeScenarioId && !!activeDevice?.id,
    staleTime: 0,
    refetchOnMount: 'always'
  });

  useEffect(() => {
    if (!pairKey || !variableQuery.data) return;
    if (dirtyKeys[pairKey]) return;
    const savedVars = variableQuery.data?.vars ?? {};
    const nextDraft = formatDeviceVarsJson(savedVars);
    const nextEnabled = Object.keys(savedVars).length > 0;
    setDrafts((prev) => {
      if (prev[pairKey] === nextDraft) return prev;
      return {
        ...prev,
        [pairKey]: nextDraft
      };
    });
    setDeviceVarEnabled((prev) => {
      if (prev[pairKey] === nextEnabled) return prev;
      return {
        ...prev,
        [pairKey]: nextEnabled
      };
    });
  }, [
    activeScenario?.variables,
    dirtyKeys,
    pairKey,
    variableQuery.data,
    variableQuery.dataUpdatedAt
  ]);

  const allSelected =
    allSerials.length > 0 && allSerials.every((s) => selected.has(s));
  const someSelected = allSerials.some((s) => selected.has(s));
  const currentDraft = pairKey
    ? (drafts[pairKey] ??
      (variableQuery.isLoading ? '' : formatDeviceVarsJson({})))
    : formatDeviceVarsJson({});
  const currentDeviceVarsEnabled = pairKey
    ? deviceVarEnabled[pairKey] === true
    : false;
  const parseMsgs = useMemo(
    () => ({
      invalidJson: tVars('parseInvalidJson'),
      invalidRoot: tVars('parseInvalidRoot')
    }),
    [tVars]
  );
  const currentJsonError = useMemo(() => {
    if (variableQuery.isLoading || !currentDeviceVarsEnabled) return '';
    try {
      parseDeviceVarsJson(currentDraft, parseMsgs);
      return '';
    } catch (err) {
      return err instanceof Error ? err.message : tVars('parseUnknown');
    }
  }, [
    currentDeviceVarsEnabled,
    currentDraft,
    variableQuery.isLoading,
    parseMsgs,
    tVars
  ]);

  const globalVariablesPreview = useMemo(
    () =>
      mergeCampaignScenarioVariables(
        effectiveCampaignVariables,
        activeScenario?.variables
      ),
    [effectiveCampaignVariables, activeScenario?.variables]
  );

  const toggle = (serial: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(serial)) next.delete(serial);
      else next.add(serial);
      return next;
    });
  };

  const toggleAll = () => {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(allSerials));
    }
  };

  const handleDraftChange = (value: string) => {
    if (!pairKey) return;
    setDrafts((prev) => ({ ...prev, [pairKey]: value }));
    setDirtyKeys((prev) => ({ ...prev, [pairKey]: true }));
  };

  const handleDeviceVarsToggle = (enabled: boolean) => {
    if (!pairKey) return;
    setDeviceVarEnabled((prev) => ({ ...prev, [pairKey]: enabled }));
    setDrafts((prev) => ({
      ...prev,
      [pairKey]: prev[pairKey] ?? formatDeviceVarsJson({})
    }));
    setDirtyKeys((prev) => ({ ...prev, [pairKey]: true }));
  };

  const saveDirtyDrafts = async () => {
    const keys = Object.keys(dirtyKeys);
    for (const key of keys) {
      if (deviceVarEnabled[key] !== true) continue;
      try {
        parseDeviceVarsJson(drafts[key] ?? '{}', parseMsgs);
      } catch (err) {
        const [scenarioId, deviceId] = key.split('::');
        setActiveScenarioId(scenarioId);
        setActiveDeviceId(deviceId);
        toast.error(err instanceof Error ? err.message : tVars('parseUnknown'));
        return false;
      }
    }

    if (!keys.length) return true;

    setIsSaving(true);
    try {
      const results = await Promise.all(
        keys.map((key) => {
          const [scenarioId, deviceId] = key.split('::');
          const vars =
            deviceVarEnabled[key] === true
              ? parseDeviceVarsJson(drafts[key] ?? '{}', parseMsgs)
              : {};
          return campaignsApi.replaceScenarioDeviceVariables(
            campaignId,
            scenarioId,
            deviceId,
            {
              vars
            }
          );
        })
      );
      results.forEach((result) => {
        qc.setQueryData(
          [
            'campaign-device-variables',
            campaignId,
            result.scenario_id,
            result.device_id
          ],
          result
        );
      });
      keys.forEach((key) => {
        const [scenarioId, deviceId] = key.split('::');
        qc.invalidateQueries({
          queryKey: [
            'campaign-device-variables',
            campaignId,
            scenarioId,
            deviceId
          ]
        });
      });
      setDirtyKeys({});
      return true;
    } catch {
      toast.error(tVars('saveFailed'));
      return false;
    } finally {
      setIsSaving(false);
    }
  };

  const formatScenarioLintIssue = (
    issue: ScenarioLintPreflightResult['issues'][number]
  ) =>
    tScenarioLintPreflight(`issues.${issue.kind}`, {
      variable: issue.variable,
      source: issue.source,
      producerStepType: issue.producerStepType ?? '',
      producerPathKey: issue.producerPathKey ?? ''
    });

  const scenarioLintInitialVariables = (scenario: ScenarioOut): string[] => {
    const names = new Set<string>();
    for (const key of Object.keys(effectiveCampaignVariables ?? {})) {
      if (key.trim()) names.add(key);
    }
    for (const key of Object.keys(scenario.variables ?? {})) {
      if (key.trim()) names.add(key);
    }
    return Array.from(names);
  };

  const runScenarioLintPreflight = async () => {
    const scenariosToCheck = scenarios.filter((scenario) =>
      Array.isArray(scenario.steps)
    );
    if (scenariosToCheck.length === 0) return true;

    const checks = scenariosToCheck.map((scenario) => ({
      scenario,
      result: scenarioLintPreflightForSteps(
        scenario.steps as FlowStep[],
        scenarioLintInitialVariables(scenario)
      )
    }));
    const failed = checks.filter((check) => check.result.hasCritical);
    const warned = checks.filter(
      (check) => check.result.warningIssues.length > 0
    );
    const totalCritical = failed.reduce(
      (sum, check) => sum + check.result.criticalIssues.length,
      0
    );
    const issueSummary = failed
      .slice(0, 3)
      .map(
        ({ scenario, result }) =>
          `${scenario.name}: ${scenarioLintSummary(result.criticalIssues, {
            moreLabel: (count) =>
              tScenarioLintPreflight('summaryMore', { count }),
            formatIssue: formatScenarioLintIssue
          })}`
      )
      .join('; ');
    const warningSummary = warned
      .slice(0, 3)
      .map(
        ({ scenario, result }) =>
          `${scenario.name}: ${scenarioLintSummary(result.warningIssues, {
            moreLabel: (count) =>
              tScenarioLintPreflight('summaryMore', { count }),
            formatIssue: formatScenarioLintIssue
          })}`
      )
      .join('; ');

    if (warningSummary) {
      toast.warning(tScenarioLintPreflight('warningToast', { warningSummary }));
    }
    if (failed.length === 0) return true;

    return confirm({
      title: tScenarioLintPreflight('confirmTitle'),
      description: tScenarioLintPreflight('confirmDescription', {
        context: tScenarioLintPreflight('campaignRunContext'),
        count: totalCritical,
        summary: issueSummary
      }),
      confirmText: tScenarioLintPreflight('confirmRun'),
      cancelText: tScenarioLintPreflight('cancelRun'),
      confirmVariant: 'destructive',
      zIndex: 10_000
    });
  };

  const runCapabilityPreflight = async (serials: string[]) => {
    const scenariosToCheck = scenarios.filter((scenario) =>
      Array.isArray(scenario.steps)
    );
    if (scenariosToCheck.length === 0) return true;

    setIsCapabilityChecking(true);
    try {
      const checks = await Promise.all(
        serials.flatMap((serial) =>
          scenariosToCheck.map(async (scenario) => ({
            serial,
            scenario,
            result: await scenarioDeviceCapabilitiesApi.preflight(serial, {
              steps: scenario.steps
            })
          }))
        )
      );
      const failed = checks.filter((check) => !check.result.preflight.ok);
      const warned = checks.filter(
        (check) => check.result.preflight.warnings.length > 0
      );
      const issueSummary = failed
        .slice(0, 3)
        .map(
          ({ serial, scenario, result }) =>
            `${serial}/${scenario.name}: ${
              scenarioCapabilityIssueSummary(result.preflight, {
                moreLabel: (count) =>
                  tCapabilityPreflight('summaryMore', { count })
              }) || tCapabilityPreflight('missingCapability')
            }`
        )
        .join('; ');
      const warningSummary = warned
        .slice(0, 3)
        .map(
          ({ serial, scenario, result }) =>
            `${serial}/${scenario.name}: ${
              scenarioCapabilityWarningSummary(result.preflight, {
                moreLabel: (count) =>
                  tCapabilityPreflight('summaryMore', { count })
              }) || tCapabilityPreflight('unknownCapability')
            }`
        )
        .join('; ');
      setCapabilityPreflight({
        ok: failed.length === 0,
        checked: checks.length,
        issueSummary,
        warningSummary
      });
      if (failed.length > 0) {
        toast.error(
          issueSummary
            ? tCapabilityPreflight('campaignBlockedToast', {
                summary: issueSummary
              })
            : tCapabilityPreflight('campaignBlockedToastFallback')
        );
        return false;
      }
      if (warningSummary) {
        toast.warning(
          tCapabilityPreflight('campaignWarningToast', {
            summary: warningSummary
          })
        );
      }
      return true;
    } catch (error) {
      toast.error(
        formatFarmApiError(
          error,
          tCapabilityPreflight('campaignFailedFallback')
        )
      );
      return false;
    } finally {
      setIsCapabilityChecking(false);
    }
  };

  const handleRun = async () => {
    if (!(await saveDirtyDrafts())) return;
    if (!(await runScenarioLintPreflight())) return;
    const serials = allSerials.filter((s) => selected.has(s));
    if (!(await runCapabilityPreflight(serials))) return;
    // If all selected, pass undefined so backend uses all assigned devices
    onConfirm(serials.length === allSerials.length ? undefined : serials);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent className='flex max-h-[92vh] min-w-[800px] max-w-5xl flex-col gap-0 overflow-hidden p-0 sm:w-full'>
        <DialogHeader className='shrink-0 space-y-0 border-b px-5 py-4 pr-12 text-left'>
          <DialogTitle className='flex items-start gap-2 text-base font-semibold leading-snug'>
            <Play size={16} className='mt-0.5 shrink-0 text-primary' />
            <span className='min-w-0 break-words'>{tList('titleRun')}</span>
          </DialogTitle>
          {activeScenario ? (
            scenarios.length > 1 ? (
              <div className='mt-3 min-w-0'>
                <Select
                  value={activeScenarioId}
                  onValueChange={setActiveScenarioId}
                >
                  <SelectTrigger
                    size='sm'
                    className='h-auto min-h-9 w-full min-w-0 whitespace-normal py-2 text-left text-xs leading-snug [&_[data-slot=select-value]]:line-clamp-2 [&_[data-slot=select-value]]:whitespace-normal'
                    title={activeScenario.name}
                  >
                    <SelectValue
                      placeholder={tList('runDialogScenarioPlaceholder')}
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {scenarios.map((scenario) => (
                      <SelectItem key={scenario.id} value={scenario.id}>
                        {scenario.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : (
              <p
                className='mt-2 line-clamp-3 text-xs font-medium leading-snug text-foreground'
                title={activeScenario.name}
              >
                {activeScenario.name}
              </p>
            )
          ) : null}
        </DialogHeader>

        {devices.length === 0 || scenarios.length === 0 ? (
          <p className='shrink-0 px-5 py-6 text-center text-xs text-muted-foreground'>
            {tList('runDialogNotReady')}
          </p>
        ) : (
          <div className='flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden px-5'>
            {isCapabilityChecking || capabilityPreflight ? (
              <Alert
                variant={
                  capabilityPreflight && !capabilityPreflight.ok
                    ? 'destructive'
                    : 'default'
                }
                className='mt-3 rounded-md py-2 text-xs'
              >
                {isCapabilityChecking ? (
                  <Loader2 className='size-3.5 animate-spin' />
                ) : (
                  <AlertCircle className='size-3.5' />
                )}
                <AlertTitle className='text-xs'>
                  {isCapabilityChecking
                    ? tCapabilityPreflight('checkingTitle')
                    : capabilityPreflight?.ok
                      ? tCapabilityPreflight('campaignOkTitle')
                      : tCapabilityPreflight('campaignBlockedTitle')}
                </AlertTitle>
                <AlertDescription className='text-xs'>
                  {capabilityPreflight?.ok
                    ? capabilityPreflight.warningSummary ||
                      tCapabilityPreflight('campaignReadyDescription', {
                        count: capabilityPreflight.checked
                      })
                    : capabilityPreflight
                      ? capabilityPreflight.issueSummary ||
                        tCapabilityPreflight('campaignMissingDescription')
                      : tCapabilityPreflight('checkingCampaignDescription')}
                </AlertDescription>
              </Alert>
            ) : null}
            <div className='grid min-h-0 min-w-0 flex-1 grid-cols-1 divide-y divide-border pb-2 pt-4 md:grid-cols-[minmax(200px,280px)_minmax(0,1fr)] md:divide-x md:divide-y-0'>
              <div className='min-h-0 max-md:max-h-[40vh] max-md:overflow-y-auto md:py-4 md:pr-4'>
                <button
                  type='button'
                  onClick={toggleAll}
                  className='mb-2 flex w-full items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-muted/60'
                >
                  {allSelected ? (
                    <CheckSquare size={14} className='text-primary' />
                  ) : (
                    <Square size={14} className='text-muted-foreground' />
                  )}
                  <span className='font-medium'>
                    {tList('runDialogSelectAll')}
                  </span>
                  <Badge variant='secondary' className='ml-auto text-[10px]'>
                    {allSerials.length}
                  </Badge>
                </button>

                <div className='max-h-[min(64vh,28rem)] space-y-1 overflow-y-auto pr-1 md:max-h-none md:overflow-visible'>
                  {devices.map((device) => {
                    const isChecked = selected.has(device.serial);
                    const isActive = activeDevice?.id === device.id;
                    return (
                      <div
                        key={device.id}
                        className={cn(
                          'flex items-center gap-1 rounded border border-transparent px-1 py-1',
                          isActive && 'border-primary/30 bg-primary/[0.06]'
                        )}
                      >
                        <button
                          type='button'
                          onClick={() => toggle(device.serial)}
                          className='flex h-7 w-7 shrink-0 items-center justify-center rounded hover:bg-muted'
                          aria-label={
                            isChecked
                              ? tList('runDialogAriaDeselectDevice')
                              : tList('runDialogAriaSelectDevice')
                          }
                        >
                          {isChecked ? (
                            <CheckSquare size={13} className='text-primary' />
                          ) : (
                            <Square
                              size={13}
                              className='text-muted-foreground'
                            />
                          )}
                        </button>
                        <button
                          type='button'
                          onClick={() => setActiveDeviceId(device.id)}
                          className='flex min-w-0 flex-1 items-center gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-muted/60'
                        >
                          <Smartphone
                            size={12}
                            className='shrink-0 text-muted-foreground'
                          />
                          <span className='min-w-0 truncate font-mono'>
                            {device.serial}
                          </span>
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className='flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden md:py-4 md:pl-4'>
                <DeviceVarsJsonPanel
                  enabled={currentDeviceVarsEnabled}
                  onEnabledChange={handleDeviceVarsToggle}
                  draft={currentDraft}
                  onDraftChange={handleDraftChange}
                  loading={
                    variableQuery.isLoading || campaignDetailQuery.isFetching
                  }
                  jsonError={currentJsonError}
                  deviceLabel={activeDevice?.serial}
                  baseVariables={globalVariablesPreview}
                  globalVariablesPreview={globalVariablesPreview}
                  className='flex min-h-0 min-w-0 flex-1 flex-col'
                  editorClassName='min-h-[200px] flex-1 md:min-h-[260px]'
                  emptyClassName='flex min-h-[200px] flex-1 flex-col md:min-h-[260px]'
                />
              </div>
            </div>
          </div>
        )}

        <DialogFooter className='shrink-0 gap-2 border-t bg-background px-5 py-4'>
          <Button
            size='sm'
            variant='outline'
            className='h-7 text-xs'
            onClick={onClose}
          >
            {tModal('cancel')}
          </Button>
          <Button
            size='sm'
            className='h-7 gap-1.5 text-xs'
            disabled={
              isRunning ||
              isSaving ||
              isCapabilityChecking ||
              !someSelected ||
              !!currentJsonError
            }
            onClick={handleRun}
          >
            {isSaving || isCapabilityChecking ? (
              <Loader2 size={12} className='animate-spin' />
            ) : (
              <Play size={12} />
            )}
            {selected.size > 0 && selected.size < allSerials.length
              ? tList('runDialogRunCount', { count: selected.size })
              : tList('runDialogRun')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
