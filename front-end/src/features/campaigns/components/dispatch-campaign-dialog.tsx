'use client';

import { useEffect, useMemo, useState } from 'react';
import { CheckSquare, Eye, Loader2, Smartphone, Square } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
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
  externalEntitiesApi,
  normalizeCampaignOut
} from '../services/api';
import type {
  CampaignDispatchIn,
  CampaignDispatchPreviewOut,
  ExternalEntityCatalogItem
} from '../services/api';
import type { CampaignDeviceOut, CampaignOut } from '../types';
import {
  buildSourcePoolInput,
  isAllocatableSourceStatus,
  listSourcePoolOptions
} from './dispatch-source-pool';

function deviceLabel(d: CampaignDeviceOut) {
  return d.name?.trim() || d.serial || '—';
}

function findSourcePoolStep(steps: unknown): FlowSourcePoolStep | null {
  if (!Array.isArray(steps)) return null;
  for (const step of steps) {
    if (!step || typeof step !== 'object') continue;
    const row = step as Record<string, unknown>;
    if (row.type === 'use_source_pool') {
      return {
        platform: String(row.platform || 'facebook'),
        entityType: String(row.entity_type || 'group'),
        search: typeof row.search === 'string' ? row.search : '',
        outputPrefix:
          typeof row.output_prefix === 'string' ? row.output_prefix : 'GROUP'
      };
    }
    for (const key of ['steps', 'then', 'else']) {
      const nested = findSourcePoolStep(row[key]);
      if (nested) return nested;
    }
    if (Array.isArray(row.branches)) {
      for (const branch of row.branches) {
        const nested = findSourcePoolStep(
          branch && typeof branch === 'object'
            ? (branch as Record<string, unknown>).steps
            : null
        );
        if (nested) return nested;
      }
    }
  }
  return null;
}

type FlowSourcePoolStep = {
  platform: string;
  entityType: string;
  search: string;
  outputPrefix: string;
};

type SourceEntityOption = {
  id: string;
  platform: string;
  entity_type: string;
  display_name: string;
};

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
  const [externalEntities, setExternalEntities] = useState<
    ExternalEntityCatalogItem[]
  >([]);
  const [sourcePoolEnabled, setSourcePoolEnabled] = useState(false);
  const [sourcePoolKey, setSourcePoolKey] = useState('');
  const [sourceSearch, setSourceSearch] = useState('');
  const [sourceOutputPrefix, setSourceOutputPrefix] = useState('');
  const [sourcePreview, setSourcePreview] =
    useState<CampaignDispatchPreviewOut | null>(null);
  const [sourcePreviewKey, setSourcePreviewKey] = useState('');
  const [sourcePreviewError, setSourcePreviewError] = useState('');
  const [sourcePreviewLoading, setSourcePreviewLoading] = useState(false);
  const [sourceAssignmentOverrides, setSourceAssignmentOverrides] = useState<
    Record<string, string>
  >({});
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
  const sourcePoolFromScenario = useMemo(() => {
    for (const scenario of scenarios) {
      const sourcePool = findSourcePoolStep(scenario.steps);
      if (sourcePool) return sourcePool;
    }
    return null;
  }, [scenarios]);
  const sourcePoolFromScenarioKey = sourcePoolFromScenario
    ? `${sourcePoolFromScenario.platform.trim().toLowerCase()}::${sourcePoolFromScenario.entityType.trim().toLowerCase()}`
    : '';
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
    let cancelled = false;
    externalEntitiesApi
      .list({ limit: 500 })
      .then((result) => {
        if (!cancelled) {
          const available = result.items.filter((item) =>
            isAllocatableSourceStatus(item.status)
          );
          setExternalEntities(available);
          const options = listSourcePoolOptions(available);
          setSourcePoolKey((current) => {
            if (sourcePoolFromScenarioKey) return sourcePoolFromScenarioKey;
            return options.some((option) => option.key === current)
              ? current
              : options[0]?.key || '';
          });
        }
      })
      .catch(() => {
        if (!cancelled) setExternalEntities([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, sourcePoolFromScenarioKey]);

  useEffect(() => {
    if (!open) return;
    setSelectedIds(new Set(allDeviceIds));
    setGroupIds(new Set());
    setSourcePoolEnabled(Boolean(sourcePoolFromScenario));
    setSourcePoolKey(sourcePoolFromScenarioKey);
    setSourceSearch(sourcePoolFromScenario?.search ?? '');
    setSourceOutputPrefix(sourcePoolFromScenario?.outputPrefix ?? '');
    setSourcePreview(null);
    setSourcePreviewKey('');
    setSourcePreviewError('');
    setSourcePreviewLoading(false);
    setSourceAssignmentOverrides({});
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
    scenarioSignature,
    sourcePoolFromScenario,
    sourcePoolFromScenarioKey
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
  const sourcePoolOptions = useMemo(
    () => listSourcePoolOptions(externalEntities),
    [externalEntities]
  );
  const sourcePoolMenuOptions = useMemo(() => {
    if (!sourcePoolFromScenario || !sourcePoolFromScenarioKey) {
      return sourcePoolOptions;
    }
    if (
      sourcePoolOptions.some(
        (option) => option.key === sourcePoolFromScenarioKey
      )
    ) {
      return sourcePoolOptions;
    }
    return [
      {
        key: sourcePoolFromScenarioKey,
        platform: sourcePoolFromScenario.platform.trim().toLowerCase(),
        entityType: sourcePoolFromScenario.entityType.trim().toLowerCase(),
        count: 0
      },
      ...sourcePoolOptions
    ];
  }, [sourcePoolFromScenario, sourcePoolFromScenarioKey, sourcePoolOptions]);
  const selectedSourcePool = useMemo(
    () =>
      sourcePoolKey
        ? buildSourcePoolInput(sourcePoolKey, sourceSearch, sourceOutputPrefix)
        : null,
    [sourceOutputPrefix, sourcePoolKey, sourceSearch]
  );
  const currentSourcePreviewKey = useMemo(
    () =>
      JSON.stringify({
        device_ids: allDeviceIds.filter((id) => selectedIds.has(id)),
        device_group_ids: Array.from(groupIds).sort(),
        source_pool: selectedSourcePool
      }),
    [allDeviceIds, groupIds, selectedIds, selectedSourcePool]
  );
  const sourcePreviewCurrent =
    !sourcePoolEnabled ||
    (sourcePreview != null && sourcePreviewKey === currentSourcePreviewKey);
  const sourceEntityOptions = useMemo(() => {
    if (!selectedSourcePool) return [];
    const search = (selectedSourcePool.search ?? '').trim().toLowerCase();
    const options: SourceEntityOption[] = externalEntities
      .filter((entity) => {
        if (
          entity.platform.trim().toLowerCase() !==
            selectedSourcePool.platform.trim().toLowerCase() ||
          entity.entity_type.trim().toLowerCase() !==
            selectedSourcePool.entity_type.trim().toLowerCase()
        ) {
          return false;
        }
        if (!search) return true;
        return entity.display_name.trim().toLowerCase().includes(search);
      })
      .map((entity) => ({
        id: entity.id,
        platform: entity.platform,
        entity_type: entity.entity_type,
        display_name: entity.display_name
      }));
    const byId = new Map(options.map((entity) => [entity.id, entity]));
    for (const assignment of sourcePreview?.assignments ?? []) {
      if (byId.has(assignment.external_entity_id)) continue;
      byId.set(assignment.external_entity_id, {
        id: assignment.external_entity_id,
        platform: assignment.platform,
        entity_type: assignment.entity_type,
        display_name: assignment.display_name
      });
    }
    return Array.from(byId.values()).sort((left, right) =>
      left.display_name.localeCompare(right.display_name)
    );
  }, [externalEntities, selectedSourcePool, sourcePreview?.assignments]);
  const sourceEntityById = useMemo(
    () => new Map(sourceEntityOptions.map((entity) => [entity.id, entity])),
    [sourceEntityOptions]
  );
  const effectiveSourceAssignments = useMemo(() => {
    return (sourcePreview?.assignments ?? []).map((assignment) => {
      const externalEntityId =
        sourceAssignmentOverrides[assignment.device_id] ||
        assignment.external_entity_id;
      const entity = sourceEntityById.get(externalEntityId);
      return {
        ...assignment,
        external_entity_id: externalEntityId,
        display_name: entity?.display_name ?? assignment.display_name,
        platform: entity?.platform ?? assignment.platform,
        entity_type: entity?.entity_type ?? assignment.entity_type
      };
    });
  }, [sourceAssignmentOverrides, sourceEntityById, sourcePreview?.assignments]);
  const duplicateSourceEntityIds = useMemo(() => {
    const counts = new Map<string, number>();
    for (const assignment of effectiveSourceAssignments) {
      counts.set(
        assignment.external_entity_id,
        (counts.get(assignment.external_entity_id) ?? 0) + 1
      );
    }
    return new Set(
      Array.from(counts.entries())
        .filter(([, count]) => count > 1)
        .map(([entityId]) => entityId)
    );
  }, [effectiveSourceAssignments]);
  const hasDuplicateSourceAssignment = duplicateSourceEntityIds.size > 0;

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

  const buildDispatchBody = (
    includeAllocationSnapshot = true
  ): CampaignDispatchIn => {
    const device_ids = allDeviceIds.filter((id) => selectedIds.has(id));
    const device_group_ids = Array.from(groupIds);
    return {
      target: {
        ...(device_ids.length ? { device_ids } : {}),
        ...(device_group_ids.length ? { device_group_ids } : {})
      },
      ...(sourcePoolEnabled && selectedSourcePool
        ? {
            source_pool: selectedSourcePool,
            ...(includeAllocationSnapshot &&
            sourcePreviewCurrent &&
            sourcePreview
              ? {
                  allocation_snapshot: effectiveSourceAssignments.map(
                    (assignment) => ({
                      device_id: assignment.device_id,
                      external_entity_id: assignment.external_entity_id
                    })
                  )
                }
              : {}),
            allocation_policy: 'one_per_device' as const
          }
        : {}),
      dispatch_strategy: strategy,
      require_online: true,
      allow_partial: false
    };
  };

  const handleSourcePreview = async () => {
    if (!sourcePoolEnabled || !selectedSourcePool || !hasTarget) return;
    setSourcePreviewLoading(true);
    setSourcePreviewError('');
    try {
      const preview = await campaignsApi.previewDispatch(
        campaignId,
        buildDispatchBody(false)
      );
      setSourcePreview(preview);
      setSourcePreviewKey(currentSourcePreviewKey);
      setSourceAssignmentOverrides({});
    } catch (err) {
      setSourcePreview(null);
      setSourcePreviewKey('');
      setSourcePreviewError(formatFarmApiError(err, t('previewFailed')));
    } finally {
      setSourcePreviewLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (!(await saveDirtyDrafts())) return;
    if (!sourcePreviewCurrent) return;
    if (hasDuplicateSourceAssignment) return;
    onConfirm(buildDispatchBody());
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

              {sourcePoolMenuOptions.length > 0 && (
                <div className='space-y-2'>
                  <label className='flex cursor-pointer items-center gap-2 text-xs font-medium'>
                    <Checkbox
                      checked={sourcePoolEnabled}
                      onCheckedChange={(checked) => {
                        setSourcePoolEnabled(checked === true);
                        setSourcePreview(null);
                        setSourcePreviewKey('');
                        setSourcePreviewError('');
                        setSourceAssignmentOverrides({});
                      }}
                    />
                    {t('sourcePoolEnabled')}
                  </label>
                  {sourcePoolEnabled ? (
                    <div className='space-y-2 rounded-md border p-3'>
                      <Label className='text-[11px]'>
                        {t('sourcePoolLabel')}
                      </Label>
                      <Select
                        value={sourcePoolKey}
                        onValueChange={(value) => {
                          setSourcePoolKey(value);
                          setSourcePreviewError('');
                          setSourceAssignmentOverrides({});
                        }}
                      >
                        <SelectTrigger className='h-8 text-xs'>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {sourcePoolMenuOptions.map((option) => (
                            <SelectItem key={option.key} value={option.key}>
                              {option.platform} / {option.entityType} (
                              {option.count})
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Input
                        value={sourceSearch}
                        onChange={(event) => {
                          setSourceSearch(event.target.value);
                          setSourcePreviewError('');
                          setSourceAssignmentOverrides({});
                        }}
                        placeholder={t('sourceSearchPlaceholder')}
                        className='h-8 text-xs'
                      />
                      <p className='text-[11px] text-muted-foreground'>
                        {t('sourcePolicyHelp')}
                      </p>
                      <Button
                        type='button'
                        size='sm'
                        variant='outline'
                        className='h-7 gap-1.5 text-xs'
                        disabled={
                          sourcePreviewLoading ||
                          !hasTarget ||
                          !selectedSourcePool
                        }
                        onClick={() => void handleSourcePreview()}
                      >
                        {sourcePreviewLoading ? (
                          <Loader2 size={12} className='animate-spin' />
                        ) : (
                          <Eye size={12} />
                        )}
                        {t('previewAllocation')}
                      </Button>
                      {sourcePreviewError ? (
                        <p className='text-[11px] text-destructive'>
                          {sourcePreviewError}
                        </p>
                      ) : null}
                      {sourcePreviewCurrent && sourcePreview ? (
                        <div className='max-h-56 space-y-2 overflow-y-auto rounded bg-muted/40 p-2'>
                          <p className='text-[11px] font-medium'>
                            {t('previewSummary', {
                              assigned: effectiveSourceAssignments.length,
                              available: sourcePreview.available_source_count
                            })}
                          </p>
                          {hasDuplicateSourceAssignment ? (
                            <p className='text-[11px] text-destructive'>
                              {t('duplicateSourceAssignment')}
                            </p>
                          ) : null}
                          {effectiveSourceAssignments.map((assignment) => {
                            const selectedByOtherDevice = new Set(
                              effectiveSourceAssignments
                                .filter(
                                  (row) =>
                                    row.device_id !== assignment.device_id
                                )
                                .map((row) => row.external_entity_id)
                            );
                            return (
                              <div
                                key={assignment.device_id}
                                className='grid gap-1 rounded border bg-background/70 p-2 sm:grid-cols-[minmax(0,1fr)_minmax(12rem,1.4fr)] sm:items-center'
                              >
                                <div className='min-w-0 text-[11px]'>
                                  <p className='truncate font-medium'>
                                    {assignment.device_serial ??
                                      assignment.device_id}
                                  </p>
                                  {assignment.device_name ? (
                                    <p className='truncate text-muted-foreground'>
                                      {assignment.device_name}
                                    </p>
                                  ) : null}
                                </div>
                                <Select
                                  value={assignment.external_entity_id}
                                  onValueChange={(value) => {
                                    setSourceAssignmentOverrides((prev) => ({
                                      ...prev,
                                      [assignment.device_id]: value
                                    }));
                                    setSourcePreviewError('');
                                  }}
                                >
                                  <SelectTrigger className='h-8 min-w-0 text-xs'>
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {sourceEntityOptions.map((entity) => (
                                      <SelectItem
                                        key={entity.id}
                                        value={entity.id}
                                        disabled={selectedByOtherDevice.has(
                                          entity.id
                                        )}
                                      >
                                        {entity.display_name}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              </div>
                            );
                          })}
                        </div>
                      ) : sourcePreview && !sourcePreviewCurrent ? (
                        <p className='text-[11px] text-amber-600'>
                          {t('previewStale')}
                        </p>
                      ) : null}
                    </div>
                  ) : (
                    <p className='text-[11px] text-muted-foreground'>
                      {t('sourcePoolDisabledHelp')}
                    </p>
                  )}
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
                  loading={backendCampaignLoading}
                  jsonError={currentJsonError}
                  deviceLabel={activeDevice?.serial}
                  baseVariables={globalVariablesPreview}
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
              isDispatching ||
              isSaving ||
              !hasTarget ||
              !sourcePreviewCurrent ||
              hasDuplicateSourceAssignment ||
              !!currentJsonError
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
