'use client';

import { useEffect, useMemo, useState } from 'react';
import { CheckSquare, Loader2, Smartphone, Square } from 'lucide-react';
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
  formatInitialDeviceVars,
  mergeCampaignScenarioVariables,
  parseDeviceVarsJson,
  splitDeviceOverridesFromMerged
} from '@/components/device-vars-json-panel';
import { cn } from '@/lib/utils';
import { useDeviceGroups } from '@/features/device-groups/hooks/use-device-groups';
import { campaignsApi } from '../services/api';
import type { CampaignDeviceOut } from '../types';
import type { CampaignDispatchIn } from '../../device-farm/services/generated/DeviceFarmApi';

function deviceLabel(d: CampaignDeviceOut) {
  return d.name?.trim() || d.serial || '—';
}

export type DispatchScenarioItem = {
  id: string;
  name: string;
  variables?: Record<string, unknown>;
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
  const [isSaving, setIsSaving] = useState(false);

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
    const savedVars = perDeviceOverrides[deviceKey] ?? {};
    setDrafts((prev) => {
      if (prev[deviceKey] !== undefined) return prev;
      return {
        ...prev,
        [deviceKey]: formatInitialDeviceVars(
          savedVars,
          activeScenario?.variables
        )
      };
    });
    setDeviceVarEnabled((prev) => {
      if (prev[deviceKey] !== undefined) return prev;
      return {
        ...prev,
        [deviceKey]: Object.keys(savedVars).length > 0
      };
    });
  }, [activeScenario?.variables, deviceKey, open, perDeviceOverrides]);

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
        campaignVariables,
        activeScenario?.variables
      ),
    [campaignVariables, activeScenario?.variables]
  );

  const campaignVarsFlat = useMemo(
    () => mergeCampaignScenarioVariables(campaignVariables, undefined),
    [campaignVariables]
  );

  const currentDraft = deviceKey
    ? (drafts[deviceKey] ??
      formatInitialDeviceVars(
        perDeviceOverrides[deviceKey] ?? {},
        activeScenario?.variables
      ))
    : formatInitialDeviceVars({}, activeScenario?.variables);

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
      [deviceKey]:
        prev[deviceKey] ??
        formatInitialDeviceVars({}, activeScenario?.variables)
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
        ...perDeviceOverrides
      };
      for (const key of keys) {
        if (deviceVarEnabled[key] !== true) {
          delete nextOverrides[key];
          continue;
        }
        const merged = parseDeviceVarsJson(drafts[key] ?? '{}', parseMsgs);
        const delta = splitDeviceOverridesFromMerged(merged, campaignVarsFlat);
        if (Object.keys(delta).length) {
          nextOverrides[key] = delta;
        } else {
          delete nextOverrides[key];
        }
      }
      await campaignsApi.patchEntity(campaignId, {
        per_device_overrides: nextOverrides
      });
      qc.invalidateQueries({ queryKey: ['campaigns', campaignId] as const });
      setDirtyKeys({});
      return true;
    } catch {
      toast.error(tVars('saveFailed'));
      return false;
    } finally {
      setIsSaving(false);
    }
  };

  const handleSubmit = async () => {
    if (!(await saveDirtyDrafts())) return;
    const device_ids = allDeviceIds.filter((id) => selectedIds.has(id));
    const device_group_ids = Array.from(groupIds);
    onConfirm({
      target: {
        ...(device_ids.length ? { device_ids } : {}),
        ...(device_group_ids.length ? { device_group_ids } : {})
      },
      dispatch_strategy: strategy,
      require_online: true,
      allow_partial: false
    });
  };

  const showVarsPanel = devices.length > 0;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className='flex max-h-[92vh] min-w-[800px] max-w-5xl flex-col gap-0 overflow-hidden p-0 sm:w-full'>
        <DialogHeader className='shrink-0 space-y-0 border-b px-5 py-4 pr-12 text-left'>
          <DialogTitle>{t('title')}</DialogTitle>
          <DialogDescription className='mt-1.5 text-xs'>
            {t('description')}
          </DialogDescription>
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
                className='mt-2 line-clamp-2 text-xs font-medium leading-snug text-foreground'
                title={activeScenario.name}
              >
                {activeScenario.name}
              </p>
            )
          ) : null}
        </DialogHeader>

        <div className='flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden px-5'>
          <div
            className={cn(
              'grid min-h-0 min-w-0 flex-1 pb-2 pt-4',
              showVarsPanel
                ? 'grid-cols-1 divide-y divide-border md:grid-cols-[minmax(220px,300px)_minmax(0,1fr)] md:divide-x md:divide-y-0'
                : 'grid-cols-1'
            )}
          >
            <div className='min-h-0 space-y-4 max-md:max-h-[42vh] max-md:overflow-y-auto md:py-0 md:pr-4'>
              <div className='space-y-2'>
                <Label className='text-xs'>{t('devicesLabel')}</Label>
                {devices.length === 0 ? (
                  <p className='text-xs text-muted-foreground'>
                    {t('noDevices')}
                  </p>
                ) : (
                  <>
                    <button
                      type='button'
                      onClick={toggleAllDevices}
                      className='mb-1 flex w-full items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-muted/60'
                    >
                      {allSelected ? (
                        <CheckSquare size={14} className='text-primary' />
                      ) : (
                        <Square size={14} className='text-muted-foreground' />
                      )}
                      <span className='font-medium'>
                        {tList('runDialogSelectAll')}
                      </span>
                      <Badge
                        variant='secondary'
                        className='ml-auto text-[10px]'
                      >
                        {devices.length}
                      </Badge>
                    </button>
                    <div className='max-h-40 space-y-1 overflow-y-auto rounded-md border p-2'>
                      {devices.map((device) => {
                        const isChecked = selectedIds.has(device.id);
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
                              onClick={() => toggleDevice(device.id)}
                              className='flex h-7 w-7 shrink-0 items-center justify-center rounded hover:bg-muted'
                              aria-label={
                                isChecked
                                  ? tList('runDialogAriaDeselectDevice')
                                  : tList('runDialogAriaSelectDevice')
                              }
                            >
                              {isChecked ? (
                                <CheckSquare
                                  size={13}
                                  className='text-primary'
                                />
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
                  <Label className='text-xs'>{t('groupsLabel')}</Label>
                  <div className='max-h-28 space-y-2 overflow-y-auto rounded-md border p-3'>
                    {deviceGroups.map((group) => (
                      <label
                        key={group.id}
                        className='flex cursor-pointer items-center gap-2 text-sm'
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

              <div className='space-y-1.5'>
                <Label className='text-xs'>{t('strategyLabel')}</Label>
                <Select
                  value={strategy}
                  onValueChange={(v) =>
                    setStrategy(v === 'sequential' ? 'sequential' : 'parallel')
                  }
                >
                  <SelectTrigger className='h-8 text-xs'>
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
            </div>

            {showVarsPanel ? (
              <div className='flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden max-md:pt-4 md:pl-4 md:pt-0'>
                <DeviceVarsJsonPanel
                  enabled={currentDeviceVarsEnabled}
                  onEnabledChange={handleDeviceVarsToggle}
                  draft={currentDraft}
                  onDraftChange={handleDraftChange}
                  jsonError={currentJsonError}
                  deviceLabel={activeDevice?.serial}
                  baseVariables={activeScenario?.variables}
                  globalVariablesPreview={globalVariablesPreview}
                  className='flex min-h-0 min-w-0 flex-1 flex-col'
                  editorClassName='min-h-[180px] flex-1 md:min-h-[220px]'
                  emptyClassName='flex min-h-[180px] flex-1 flex-col md:min-h-[220px]'
                />
              </div>
            ) : null}
          </div>
        </div>

        <DialogFooter className='shrink-0 gap-2 border-t bg-background px-5 py-4'>
          <Button
            size='sm'
            variant='outline'
            className='h-7 text-xs'
            onClick={onClose}
          >
            {t('cancel')}
          </Button>
          <Button
            size='sm'
            className='h-7 gap-1.5 text-xs'
            disabled={
              isDispatching || isSaving || !hasTarget || !!currentJsonError
            }
            onClick={() => void handleSubmit()}
          >
            {isDispatching || isSaving ? (
              <Loader2 size={12} className='animate-spin' />
            ) : null}
            {isDispatching
              ? t('dispatching')
              : isSaving
                ? tVars('footerLoading')
                : t('dispatchCount', {
                    count:
                      selectedIds.size + (groupIds.size > 0 ? groupIds.size : 0)
                  })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
