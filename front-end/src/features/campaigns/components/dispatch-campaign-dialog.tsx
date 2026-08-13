'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckSquare,
  Loader2,
  Play,
  Smartphone,
  Square
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
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
  parseDeviceVarsJson,
  splitDeviceOverridesFromMerged
} from '@/components/device-vars-json-panel';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { cn } from '@/lib/utils';
import { useDeviceGroups } from '@/features/device-groups/hooks/use-device-groups';
import {
  campaignPerDeviceOverrides as readCampaignPerDeviceOverrides,
  campaignVariables as readCampaignVariables,
  campaignsApi,
  normalizeCampaignOut
} from '../services/api';
import type { CampaignDispatchIn } from '../services/api';
import type { CampaignDeviceOut, CampaignOut } from '../types';

function deviceLabel(d: CampaignDeviceOut) {
  return d.name?.trim() || d.serial || '—';
}

type DispatchStep = 'targets' | 'variables' | 'review';
const dispatchSteps: DispatchStep[] = ['targets', 'variables', 'review'];

export type DispatchScenarioItem = {
  id: string;
  name: string;
  variables?: Record<string, unknown>;
  steps?: unknown[];
};

export function DispatchCampaignDialog({
  open,
  campaignId,
  onClose,
  devices,
  scenarios = [],
  campaignVariables = {},
  perDeviceOverrides = {},
  isDispatching,
  onConfirm
}: {
  open: boolean;
  campaignId: string;
  onClose: () => void;
  devices: CampaignDeviceOut[];
  scenarios?: DispatchScenarioItem[];
  campaignVariables?: Record<string, unknown>;
  perDeviceOverrides?: Record<string, Record<string, unknown>>;
  isDispatching: boolean;
  onConfirm: (body: CampaignDispatchIn) => void;
}) {
  const t = useTranslations('campaignsFeature.dispatchDialog');
  const tList = useTranslations('campaignsFeature.list');
  const tVars = useTranslations('components.deviceVarsJson');
  const { data: deviceGroups = [] } = useDeviceGroups();
  const qc = useQueryClient();

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [groupIds, setGroupIds] = useState<Set<string>>(new Set());
  const [strategy, setStrategy] = useState<'parallel' | 'sequential'>(
    'parallel'
  );
  const [activeDeviceId, setActiveDeviceId] = useState('');
  const [activeScenarioId, setActiveScenarioId] = useState('');
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [deviceVarEnabled, setDeviceVarEnabled] = useState<
    Record<string, boolean>
  >({});
  const [dirtyKeys, setDirtyKeys] = useState<Record<string, true>>({});
  const [backendCampaign, setBackendCampaign] = useState<CampaignOut | null>(
    null
  );
  const [backendCampaignLoading, setBackendCampaignLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [step, setStep] = useState<DispatchStep>('targets');

  const allDeviceIds = useMemo(() => devices.map((d) => d.id), [devices]);
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
  const deviceKey = activeDevice?.id ?? '';
  const effectiveCampaignVariables = useMemo(
    () =>
      backendCampaign != null
        ? readCampaignVariables(backendCampaign)
        : open
          ? {}
          : campaignVariables,
    [backendCampaign, campaignVariables, open]
  );
  const effectivePerDeviceOverrides = useMemo(
    () =>
      backendCampaign != null
        ? readCampaignPerDeviceOverrides(backendCampaign)
        : open
          ? {}
          : perDeviceOverrides,
    [backendCampaign, open, perDeviceOverrides]
  );

  useEffect(() => {
    if (!open || !campaignId) {
      setBackendCampaign(null);
      setBackendCampaignLoading(false);
      return;
    }
    let cancelled = false;
    setBackendCampaign(null);
    setBackendCampaignLoading(true);
    campaignsApi
      .get(campaignId)
      .then((campaign) => {
        if (cancelled) return;
        setBackendCampaign(campaign);
        qc.setQueryData(['campaigns', campaignId], campaign);
        qc.setQueryData<CampaignOut[]>(['campaigns'], (old) =>
          old?.map((row) =>
            row.id === campaignId ? { ...row, ...campaign } : row
          )
        );
      })
      .catch(() => {
        if (!cancelled) setBackendCampaign(null);
      })
      .finally(() => {
        if (!cancelled) setBackendCampaignLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [campaignId, open, qc]);

  useEffect(() => {
    if (!open) return;
    setSelectedIds(new Set(allDeviceIds));
    setGroupIds(new Set());
    setStrategy('parallel');
    setActiveDeviceId(firstDeviceId);
    setActiveScenarioId(firstScenarioId);
    setDrafts({});
    setDeviceVarEnabled({});
    setDirtyKeys({});
    setStep('targets');
  }, [
    allDeviceIds,
    deviceSignature,
    firstDeviceId,
    firstScenarioId,
    open,
    campaignId,
    scenarioSignature
  ]);

  useEffect(() => {
    if (!open || !deviceKey) return;
    if (dirtyKeys[deviceKey]) return;
    const savedVars = effectivePerDeviceOverrides[deviceKey] ?? {};
    const nextDraft = formatDeviceVarsJson(savedVars);
    const nextEnabled = Object.prototype.hasOwnProperty.call(
      effectivePerDeviceOverrides,
      deviceKey
    );
    setDrafts((prev) => {
      if (prev[deviceKey] === nextDraft) return prev;
      return {
        ...prev,
        [deviceKey]: nextDraft
      };
    });
    setDeviceVarEnabled((prev) => {
      if (prev[deviceKey] === nextEnabled) return prev;
      return {
        ...prev,
        [deviceKey]: nextEnabled
      };
    });
  }, [
    activeScenario?.variables,
    deviceKey,
    dirtyKeys,
    effectivePerDeviceOverrides,
    open
  ]);

  const allSelected =
    allDeviceIds.length > 0 && allDeviceIds.every((id) => selectedIds.has(id));
  const someSelected = allDeviceIds.some((id) => selectedIds.has(id));
  const hasTarget = someSelected || groupIds.size > 0;
  const parseMsgs = useMemo(
    () => ({
      invalidJson: tVars('parseInvalidJson'),
      invalidRoot: tVars('parseInvalidRoot')
    }),
    [tVars]
  );

  const globalVariablesPreview = useMemo(
    () =>
      mergeCampaignScenarioVariables(
        effectiveCampaignVariables,
        activeScenario?.variables
      ),
    [effectiveCampaignVariables, activeScenario?.variables]
  );

  const globalVarsFlat = globalVariablesPreview;

  const currentDraft = deviceKey
    ? (drafts[deviceKey] ??
      formatDeviceVarsJson(effectivePerDeviceOverrides[deviceKey] ?? {}))
    : formatDeviceVarsJson({});

  const currentDeviceVarsEnabled = deviceKey
    ? deviceVarEnabled[deviceKey] === true
    : false;

  const currentJsonError = useMemo(() => {
    if (!currentDeviceVarsEnabled) return '';
    try {
      parseDeviceVarsJson(currentDraft, parseMsgs);
      return '';
    } catch (err) {
      return err instanceof Error ? err.message : tVars('parseUnknown');
    }
  }, [currentDeviceVarsEnabled, currentDraft, parseMsgs, tVars]);

  const toggleDevice = (deviceId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(deviceId)) next.delete(deviceId);
      else next.add(deviceId);
      return next;
    });
  };

  const toggleAllDevices = () => {
    if (allSelected) setSelectedIds(new Set());
    else setSelectedIds(new Set(allDeviceIds));
  };

  const toggleGroup = (groupId: string, checked: boolean) => {
    setGroupIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(groupId);
      else next.delete(groupId);
      return next;
    });
  };

  const handleDraftChange = (value: string) => {
    if (!deviceKey) return;
    setDrafts((prev) => ({ ...prev, [deviceKey]: value }));
    setDirtyKeys((prev) => ({ ...prev, [deviceKey]: true }));
  };

  const handleDeviceVarsToggle = (enabled: boolean) => {
    if (!deviceKey) return;
    setDeviceVarEnabled((prev) => ({ ...prev, [deviceKey]: enabled }));
    setDrafts((prev) => ({
      ...prev,
      [deviceKey]: prev[deviceKey] ?? formatDeviceVarsJson({})
    }));
    setDirtyKeys((prev) => ({ ...prev, [deviceKey]: true }));
  };

  const saveDirtyDrafts = async () => {
    const keys = Object.keys(dirtyKeys);
    for (const key of keys) {
      if (deviceVarEnabled[key] !== true) continue;
      try {
        parseDeviceVarsJson(drafts[key] ?? '{}', parseMsgs);
      } catch (err) {
        setActiveDeviceId(key);
        toast.error(err instanceof Error ? err.message : tVars('parseUnknown'));
        return false;
      }
    }

    if (!keys.length) return true;

    setIsSaving(true);
    try {
      const nextOverrides: Record<string, Record<string, unknown>> = {
        ...effectivePerDeviceOverrides
      };
      for (const key of keys) {
        if (deviceVarEnabled[key] !== true) {
          delete nextOverrides[key];
          continue;
        }
        const merged = parseDeviceVarsJson(drafts[key] ?? '{}', parseMsgs);
        const delta = splitDeviceOverridesFromMerged(merged, globalVarsFlat);
        nextOverrides[key] = delta;
      }
      const updated = await campaignsApi.patchEntity(campaignId, {
        per_device_overrides: nextOverrides
      });
      const campaign = normalizeCampaignOut(updated);
      if (campaign) {
        setBackendCampaign(campaign);
        qc.setQueryData(['campaigns', campaignId], campaign);
        qc.setQueryData<CampaignOut[]>(['campaigns'], (old) =>
          old?.map((row) =>
            row.id === campaignId ? { ...row, ...campaign } : row
          )
        );
      }
      qc.invalidateQueries({ queryKey: ['campaigns', campaignId] as const });
      qc.invalidateQueries({ queryKey: ['campaigns'], exact: true });
      setDirtyKeys({});
      return true;
    } catch (err) {
      toast.error(formatFarmApiError(err, tVars('saveFailed')));
      return false;
    } finally {
      setIsSaving(false);
    }
  };

  const buildDispatchBody = (): CampaignDispatchIn => {
    const device_ids = allDeviceIds.filter((id) => selectedIds.has(id));
    const device_group_ids = Array.from(groupIds);
    return {
      target: {
        ...(device_ids.length ? { device_ids } : {}),
        ...(device_group_ids.length ? { device_group_ids } : {})
      },
      dispatch_strategy: strategy,
      require_online: true,
      allow_partial: false
    };
  };

  const handleSubmit = async () => {
    if (!(await saveDirtyDrafts())) return;
    onConfirm(buildDispatchBody());
  };

  const showVarsPanel = devices.length > 0;
  const stepIndex = dispatchSteps.indexOf(step);
  const selectedDirectCount = selectedIds.size;
  const selectedGroupCount = groupIds.size;
  const dispatchTargetCount = selectedDirectCount + selectedGroupCount;
  const selectedDevices = devices.filter((device) =>
    selectedIds.has(device.id)
  );
  const selectedGroups = deviceGroups.filter((group) => groupIds.has(group.id));
  const stepLabels: Record<DispatchStep, string> = {
    targets: t('steps.targets'),
    variables: t('steps.variables'),
    review: t('steps.review')
  };

  const goBack = () => {
    if (stepIndex <= 0) {
      onClose();
      return;
    }
    setStep(dispatchSteps[stepIndex - 1] ?? 'targets');
  };

  const goNext = async () => {
    if (step === 'targets') {
      if (!hasTarget) return;
      setStep('variables');
      return;
    }
    if (step === 'variables') {
      if (currentJsonError) {
        toast.error(currentJsonError);
        return;
      }
      if (!(await saveDirtyDrafts())) return;
      setStep('review');
      return;
    }
    await handleSubmit();
  };

  const nextDisabled =
    isDispatching ||
    isSaving ||
    (step === 'targets' && !hasTarget) ||
    (step === 'variables' && !!currentJsonError) ||
    (step === 'review' && (!hasTarget || !!currentJsonError));

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className='flex h-[min(92vh,52rem)] w-[min(calc(100vw-3rem),80rem)] max-w-[calc(100vw-3rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-[80rem]'>
        <DialogHeader className='shrink-0 space-y-0 border-b px-8 py-5 pr-14 text-left'>
          <DialogTitle className='text-2xl'>{t('title')}</DialogTitle>
          <DialogDescription className='mt-2 text-sm'>
            {t('description')}
          </DialogDescription>
        </DialogHeader>

        <div className='grid grid-cols-4 border-b bg-muted/30 px-8 py-4'>
          {dispatchSteps.map((item, index) => (
            <div key={item} className='flex min-w-0 items-center gap-3'>
              <span
                className={cn(
                  'flex size-8 shrink-0 items-center justify-center rounded-full border text-sm font-semibold',
                  index <= stepIndex
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'text-muted-foreground'
                )}
              >
                {index < stepIndex ? <Check className='size-4' /> : index + 1}
              </span>
              <span
                className={cn(
                  'hidden truncate text-sm sm:block',
                  index === stepIndex
                    ? 'font-semibold'
                    : 'text-muted-foreground'
                )}
              >
                {stepLabels[item]}
              </span>
            </div>
          ))}
        </div>

        <div className='min-h-0 flex-1 overflow-y-auto px-8 py-6'>
          {step === 'targets' ? (
            <div className='grid gap-8 lg:grid-cols-[minmax(0,1fr)_24rem]'>
              <div className='min-w-0 space-y-4'>
                {activeScenario ? (
                  <div className='space-y-2'>
                    <Label className='text-sm'>{t('scenarioLabel')}</Label>
                    {scenarios.length > 1 ? (
                      <Select
                        value={activeScenarioId}
                        onValueChange={setActiveScenarioId}
                      >
                        <SelectTrigger
                          size='sm'
                          className='h-auto min-h-11 w-full min-w-0 whitespace-normal py-2.5 text-left text-sm leading-snug [&_[data-slot=select-value]]:line-clamp-2 [&_[data-slot=select-value]]:whitespace-normal'
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
                    ) : (
                      <p
                        className='line-clamp-2 rounded-md border px-4 py-3 text-sm font-medium leading-snug'
                        title={activeScenario.name}
                      >
                        {activeScenario.name}
                      </p>
                    )}
                  </div>
                ) : null}

                <div className='space-y-2'>
                  <Label className='text-sm'>{t('devicesLabel')}</Label>
                  {devices.length === 0 ? (
                    <p className='rounded-md border border-dashed px-4 py-5 text-sm text-muted-foreground'>
                      {t('noDevices')}
                    </p>
                  ) : (
                    <>
                      <button
                        type='button'
                        onClick={toggleAllDevices}
                        className='mb-2 flex w-full items-center gap-3 rounded px-3 py-2 text-sm hover:bg-muted/60'
                      >
                        {allSelected ? (
                          <CheckSquare size={16} className='text-primary' />
                        ) : (
                          <Square size={16} className='text-muted-foreground' />
                        )}
                        <span className='font-medium'>
                          {tList('runDialogSelectAll')}
                        </span>
                        <Badge variant='secondary' className='ml-auto text-xs'>
                          {devices.length}
                        </Badge>
                      </button>
                      <div className='max-h-80 space-y-1.5 overflow-y-auto rounded-md border p-3'>
                        {devices.map((device) => {
                          const isChecked = selectedIds.has(device.id);
                          const isActive = activeDevice?.id === device.id;
                          return (
                            <div
                              key={device.id}
                              className={cn(
                                'flex items-center gap-2 rounded border border-transparent px-2 py-2',
                                isActive &&
                                  'border-primary/30 bg-primary/[0.06]'
                              )}
                            >
                              <button
                                type='button'
                                onClick={() => toggleDevice(device.id)}
                                className='flex h-9 w-9 shrink-0 items-center justify-center rounded hover:bg-muted'
                                aria-label={
                                  isChecked
                                    ? tList('runDialogAriaDeselectDevice')
                                    : tList('runDialogAriaSelectDevice')
                                }
                              >
                                {isChecked ? (
                                  <CheckSquare
                                    size={16}
                                    className='text-primary'
                                  />
                                ) : (
                                  <Square
                                    size={16}
                                    className='text-muted-foreground'
                                  />
                                )}
                              </button>
                              <button
                                type='button'
                                onClick={() => setActiveDeviceId(device.id)}
                                className='flex min-w-0 flex-1 items-center gap-3 rounded px-2 py-1.5 text-left text-sm hover:bg-muted/60'
                              >
                                <Smartphone
                                  size={16}
                                  className='shrink-0 text-muted-foreground'
                                />
                                <span className='min-w-0 truncate font-mono'>
                                  {device.serial}
                                </span>
                                {device.name ? (
                                  <span className='ml-auto truncate text-muted-foreground'>
                                    {deviceLabel(device)}
                                  </span>
                                ) : null}
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    </>
                  )}
                </div>

                {deviceGroups.length > 0 && (
                  <div className='space-y-2'>
                    <Label className='text-sm'>{t('groupsLabel')}</Label>
                    <div className='max-h-52 space-y-2 overflow-y-auto rounded-md border p-4'>
                      {deviceGroups.map((group) => (
                        <label
                          key={group.id}
                          className='flex cursor-pointer items-center gap-3 text-base'
                        >
                          <Checkbox
                            checked={groupIds.has(group.id)}
                            onCheckedChange={(checked) =>
                              toggleGroup(group.id, checked === true)
                            }
                          />
                          <span className='min-w-0 truncate'>{group.name}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className='space-y-4'>
                <div className='space-y-1.5'>
                  <Label className='text-sm'>{t('strategyLabel')}</Label>
                  <Select
                    value={strategy}
                    onValueChange={(v) =>
                      setStrategy(
                        v === 'sequential' ? 'sequential' : 'parallel'
                      )
                    }
                  >
                    <SelectTrigger className='h-11 text-sm'>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value='parallel'>
                        {t('strategyParallel')}
                      </SelectItem>
                      <SelectItem value='sequential'>
                        {t('strategySequential')}
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className='space-y-4 rounded-md border bg-muted/20 p-5'>
                  <SummaryRow
                    label={t('selectedDevices')}
                    value={String(selectedDirectCount)}
                  />
                  <SummaryRow
                    label={t('selectedGroups')}
                    value={String(selectedGroupCount)}
                  />
                  <SummaryRow
                    label={t('selectedTotal')}
                    value={String(dispatchTargetCount)}
                  />
                </div>
              </div>
            </div>
          ) : null}

          {step === 'variables' ? (
            <div
              className={cn(
                'grid gap-8',
                showVarsPanel
                  ? 'lg:grid-cols-[minmax(18rem,24rem)_minmax(0,1fr)]'
                  : 'grid-cols-1'
              )}
            >
              <div className='min-w-0 space-y-2'>
                <Label className='text-sm'>{t('devicesLabel')}</Label>
                {devices.length === 0 ? (
                  <p className='rounded-md border border-dashed px-4 py-5 text-sm text-muted-foreground'>
                    {t('noDevices')}
                  </p>
                ) : (
                  <div className='max-h-[38rem] space-y-1.5 overflow-y-auto rounded-md border p-3'>
                    {devices.map((device) => {
                      const isActive = activeDevice?.id === device.id;
                      const hasOverride =
                        deviceVarEnabled[device.id] === true ||
                        Object.prototype.hasOwnProperty.call(
                          effectivePerDeviceOverrides,
                          device.id
                        );
                      return (
                        <button
                          key={device.id}
                          type='button'
                          onClick={() => setActiveDeviceId(device.id)}
                          className={cn(
                            'flex w-full min-w-0 items-center gap-3 rounded border border-transparent px-3 py-2.5 text-left text-sm hover:bg-muted/60',
                            isActive && 'border-primary/30 bg-primary/[0.06]'
                          )}
                        >
                          <Smartphone
                            size={16}
                            className='shrink-0 text-muted-foreground'
                          />
                          <span className='min-w-0 flex-1 truncate font-mono'>
                            {device.serial}
                          </span>
                          {hasOverride ? (
                            <Badge
                              variant='secondary'
                              className='shrink-0 text-xs'
                            >
                              {t('overrideBadge')}
                            </Badge>
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {showVarsPanel ? (
                <div className='flex min-h-[38rem] min-w-0 flex-col overflow-hidden'>
                  <DeviceVarsJsonPanel
                    enabled={currentDeviceVarsEnabled}
                    onEnabledChange={handleDeviceVarsToggle}
                    draft={currentDraft}
                    onDraftChange={handleDraftChange}
                    loading={backendCampaignLoading}
                    jsonError={currentJsonError}
                    deviceLabel={activeDevice?.serial}
                    baseVariables={globalVariablesPreview}
                    globalVariablesPreview={globalVariablesPreview}
                    className='flex min-h-0 min-w-0 flex-1 flex-col'
                    editorClassName='min-h-[420px] flex-1'
                    emptyClassName='flex min-h-[420px] flex-1 flex-col'
                  />
                </div>
              ) : null}
            </div>
          ) : null}

          {step === 'review' ? (
            <div className='space-y-4'>
              <div className='grid gap-3 sm:grid-cols-2'>
                <div className='space-y-4 rounded-md border p-5'>
                  <p className='text-base font-semibold'>
                    {t('reviewTargets')}
                  </p>
                  <SummaryRow
                    label={t('selectedDevices')}
                    value={String(selectedDirectCount)}
                  />
                  <SummaryRow
                    label={t('selectedGroups')}
                    value={String(selectedGroupCount)}
                  />
                  <SummaryRow
                    label={t('reviewStrategy')}
                    value={
                      strategy === 'sequential'
                        ? t('strategySequentialShort')
                        : t('strategyParallelShort')
                    }
                  />
                </div>
                <div className='space-y-4 rounded-md border p-5'>
                  <p className='text-base font-semibold'>{t('reviewSetup')}</p>
                  <SummaryRow
                    label={t('reviewVariables')}
                    value={t('reviewVariableCount', {
                      count: Object.keys(effectivePerDeviceOverrides).length
                    })}
                  />
                </div>
              </div>

              {selectedDevices.length > 0 ? (
                <div className='rounded-md border p-5'>
                  <p className='mb-3 text-base font-semibold'>
                    {t('selectedDeviceList')}
                  </p>
                  <div className='flex flex-wrap gap-2'>
                    {selectedDevices.map((device) => (
                      <Badge key={device.id} variant='secondary'>
                        {device.serial}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}

              {selectedGroups.length > 0 ? (
                <div className='rounded-md border p-5'>
                  <p className='mb-3 text-base font-semibold'>
                    {t('selectedGroupList')}
                  </p>
                  <div className='flex flex-wrap gap-2'>
                    {selectedGroups.map((group) => (
                      <Badge key={group.id} variant='outline'>
                        {group.name}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        <DialogFooter className='flex-row items-center justify-between border-t bg-muted/20 px-8 py-5 sm:justify-between'>
          <Button
            variant='ghost'
            className='h-11 px-5 text-base'
            onClick={goBack}
            disabled={isDispatching || isSaving}
          >
            {stepIndex > 0 ? <ArrowLeft className='mr-1.5 size-4' /> : null}
            {stepIndex === 0 ? t('cancel') : t('back')}
          </Button>
          <Button
            className='h-11 gap-2 px-6 text-base'
            disabled={nextDisabled}
            onClick={() => void goNext()}
          >
            {isDispatching || isSaving ? (
              <Loader2 className='size-4 animate-spin' />
            ) : step === 'review' ? (
              <Play className='size-4' />
            ) : null}
            {isDispatching
              ? t('dispatching')
              : isSaving
                ? tVars('footerLoading')
                : step === 'review'
                  ? t('dispatchCount', { count: dispatchTargetCount })
                  : t('next')}
            {step !== 'review' && !isDispatching && !isSaving ? (
              <ArrowRight className='size-4' />
            ) : null}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className='flex items-center justify-between gap-4 text-sm'>
      <span className='min-w-0 truncate text-muted-foreground'>{label}</span>
      <span className='shrink-0 text-right text-base font-semibold'>
        {value}
      </span>
    </div>
  );
}
