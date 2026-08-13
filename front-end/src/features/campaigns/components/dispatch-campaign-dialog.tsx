'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckSquare,
  Eye,
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

type DispatchStep = 'targets' | 'variables' | 'source' | 'review';
const dispatchSteps: DispatchStep[] = [
  'targets',
  'variables',
  'source',
  'review'
];

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

  const applyExternalEntityList = useCallback(
    (items: ExternalEntityCatalogItem[]) => {
      const available = items.filter((item) =>
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
    },
    [sourcePoolFromScenarioKey]
  );

  const loadExternalEntities = useCallback(async () => {
    const result = await externalEntitiesApi.list({ limit: 500 });
    return result.items;
  }, []);

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
    loadExternalEntities()
      .then((items) => {
        if (!cancelled) applyExternalEntityList(items);
      })
      .catch(() => {
        if (!cancelled) setExternalEntities([]);
      });
    return () => {
      cancelled = true;
    };
  }, [applyExternalEntityList, loadExternalEntities, open]);

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
    setStep('targets');
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
    source: t('steps.source'),
    review: t('steps.review')
  };
  const sourceStepBlocked =
    sourcePoolEnabled &&
    (!sourcePreviewCurrent || !sourcePreview || hasDuplicateSourceAssignment);

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
      setStep('source');
      return;
    }
    if (step === 'source') {
      if (sourceStepBlocked) {
        toast.error(
          hasDuplicateSourceAssignment
            ? t('duplicateSourceAssignment')
            : t('previewRequired')
        );
        return;
      }
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
    (step === 'source' && sourceStepBlocked) ||
    (step === 'review' &&
      (!hasTarget ||
        !sourcePreviewCurrent ||
        hasDuplicateSourceAssignment ||
        !!currentJsonError));

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className='flex max-h-[92vh] w-[min(calc(100vw-2rem),56rem)] max-w-none flex-col gap-0 overflow-hidden p-0'>
        <DialogHeader className='shrink-0 space-y-0 border-b px-5 py-4 pr-12 text-left'>
          <DialogTitle>{t('title')}</DialogTitle>
          <DialogDescription className='mt-1.5 text-xs'>
            {t('description')}
          </DialogDescription>
        </DialogHeader>

        <div className='grid grid-cols-4 border-b bg-muted/30 px-3 py-3 sm:px-5'>
          {dispatchSteps.map((item, index) => (
            <div key={item} className='flex min-w-0 items-center gap-2'>
              <span
                className={cn(
                  'flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold',
                  index <= stepIndex
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'text-muted-foreground'
                )}
              >
                {index < stepIndex ? <Check className='size-3.5' /> : index + 1}
              </span>
              <span
                className={cn(
                  'hidden truncate text-xs sm:block',
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

        <div className='min-h-0 flex-1 overflow-y-auto px-5 py-5'>
          {step === 'targets' ? (
            <div className='mx-auto grid max-w-3xl gap-5 lg:grid-cols-[minmax(0,1fr)_16rem]'>
              <div className='min-w-0 space-y-4'>
                {activeScenario ? (
                  <div className='space-y-2'>
                    <Label className='text-xs'>{t('scenarioLabel')}</Label>
                    {scenarios.length > 1 ? (
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
                    ) : (
                      <p
                        className='line-clamp-2 rounded-md border px-3 py-2 text-xs font-medium leading-snug'
                        title={activeScenario.name}
                      >
                        {activeScenario.name}
                      </p>
                    )}
                  </div>
                ) : null}

                <div className='space-y-2'>
                  <Label className='text-xs'>{t('devicesLabel')}</Label>
                  {devices.length === 0 ? (
                    <p className='rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground'>
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
                      <div className='max-h-56 space-y-1 overflow-y-auto rounded-md border p-2'>
                        {devices.map((device) => {
                          const isChecked = selectedIds.has(device.id);
                          const isActive = activeDevice?.id === device.id;
                          return (
                            <div
                              key={device.id}
                              className={cn(
                                'flex items-center gap-1 rounded border border-transparent px-1 py-1',
                                isActive &&
                                  'border-primary/30 bg-primary/[0.06]'
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
                    <div className='max-h-36 space-y-2 overflow-y-auto rounded-md border p-3'>
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
              </div>

              <div className='space-y-4'>
                <div className='space-y-1.5'>
                  <Label className='text-xs'>{t('strategyLabel')}</Label>
                  <Select
                    value={strategy}
                    onValueChange={(v) =>
                      setStrategy(
                        v === 'sequential' ? 'sequential' : 'parallel'
                      )
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
                <div className='space-y-3 rounded-md border bg-muted/20 p-3'>
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
                'mx-auto grid max-w-4xl gap-5',
                showVarsPanel
                  ? 'lg:grid-cols-[minmax(14rem,18rem)_minmax(0,1fr)]'
                  : 'grid-cols-1'
              )}
            >
              <div className='min-w-0 space-y-2'>
                <Label className='text-xs'>{t('devicesLabel')}</Label>
                {devices.length === 0 ? (
                  <p className='rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground'>
                    {t('noDevices')}
                  </p>
                ) : (
                  <div className='max-h-[28rem] space-y-1 overflow-y-auto rounded-md border p-2'>
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
                            'flex w-full min-w-0 items-center gap-2 rounded border border-transparent px-2 py-2 text-left text-xs hover:bg-muted/60',
                            isActive && 'border-primary/30 bg-primary/[0.06]'
                          )}
                        >
                          <Smartphone
                            size={12}
                            className='shrink-0 text-muted-foreground'
                          />
                          <span className='min-w-0 flex-1 truncate font-mono'>
                            {device.serial}
                          </span>
                          {hasOverride ? (
                            <Badge
                              variant='secondary'
                              className='shrink-0 text-[10px]'
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
                <div className='flex min-h-[28rem] min-w-0 flex-col overflow-hidden'>
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
                    editorClassName='min-h-[220px] flex-1'
                    emptyClassName='flex min-h-[220px] flex-1 flex-col'
                  />
                </div>
              ) : null}
            </div>
          ) : null}

          {step === 'source' ? (
            <div className='mx-auto max-w-3xl space-y-4'>
              {sourcePoolMenuOptions.length > 0 ? (
                <div className='space-y-3'>
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
                    <div className='space-y-3 rounded-md border p-3'>
                      <div className='grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]'>
                        <div className='space-y-1.5'>
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
                        </div>
                        <div className='space-y-1.5'>
                          <Label className='text-[11px]'>
                            {t('sourceSearchLabel')}
                          </Label>
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
                        </div>
                      </div>
                      <p className='text-[11px] text-muted-foreground'>
                        {t('sourcePolicyHelp')}
                      </p>
                      <div className='flex flex-wrap items-center gap-2'>
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
                        {sourcePoolEnabled &&
                        !sourcePreviewLoading &&
                        !sourcePreviewCurrent ? (
                          <span className='text-[11px] text-muted-foreground'>
                            {t('previewRequired')}
                          </span>
                        ) : null}
                      </div>
                      {sourcePreviewError ? (
                        <p className='text-[11px] text-destructive'>
                          {sourcePreviewError}
                        </p>
                      ) : null}
                      {sourcePreviewCurrent && sourcePreview ? (
                        <div className='max-h-[22rem] space-y-2 overflow-y-auto rounded-md bg-muted/40 p-2'>
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
                                className='grid gap-1 rounded-md border bg-background/70 p-2 sm:grid-cols-[minmax(0,1fr)_minmax(12rem,1.4fr)] sm:items-center'
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
                    <p className='rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground'>
                      {t('sourcePoolDisabledHelp')}
                    </p>
                  )}
                </div>
              ) : (
                <p className='rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground'>
                  {t('sourceUnavailable')}
                </p>
              )}
            </div>
          ) : null}

          {step === 'review' ? (
            <div className='mx-auto max-w-3xl space-y-4'>
              <div className='grid gap-3 sm:grid-cols-2'>
                <div className='space-y-3 rounded-md border p-4'>
                  <p className='text-sm font-semibold'>{t('reviewTargets')}</p>
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
                <div className='space-y-3 rounded-md border p-4'>
                  <p className='text-sm font-semibold'>{t('reviewSetup')}</p>
                  <SummaryRow
                    label={t('reviewVariables')}
                    value={t('reviewVariableCount', {
                      count: Object.keys(effectivePerDeviceOverrides).length
                    })}
                  />
                  <SummaryRow
                    label={t('reviewSource')}
                    value={
                      sourcePoolEnabled && sourcePreview
                        ? t('reviewSourceCount', {
                            count: effectiveSourceAssignments.length
                          })
                        : t('reviewSourceDisabled')
                    }
                  />
                </div>
              </div>

              {selectedDevices.length > 0 ? (
                <div className='rounded-md border p-4'>
                  <p className='mb-2 text-sm font-semibold'>
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
                <div className='rounded-md border p-4'>
                  <p className='mb-2 text-sm font-semibold'>
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

        <DialogFooter className='flex-row items-center justify-between border-t bg-muted/20 px-5 py-4 sm:justify-between'>
          <Button
            variant='ghost'
            onClick={goBack}
            disabled={isDispatching || isSaving}
          >
            {stepIndex > 0 ? <ArrowLeft className='mr-1.5 size-4' /> : null}
            {stepIndex === 0 ? t('cancel') : t('back')}
          </Button>
          <Button
            className='gap-1.5'
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
    <div className='flex items-center justify-between gap-3 text-xs'>
      <span className='min-w-0 truncate text-muted-foreground'>{label}</span>
      <span className='shrink-0 text-right font-medium'>{value}</span>
    </div>
  );
}
