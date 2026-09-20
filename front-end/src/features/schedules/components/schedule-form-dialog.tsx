'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { useLocale, useTranslations } from 'next-intl';
import {
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  Search
} from 'lucide-react';
import { useCreateSchedule, useUpdateSchedule } from '../hooks/use-schedules';
import { useCampaigns } from '@/features/campaigns/hooks/use-campaigns';
import { useOrgScenarios } from '@/features/org-scenarios/hooks/use-org-scenarios';
import { isOrgScenarioVisibleInCampaignPicker } from '@/features/org-scenarios/lib/campaign-scenario-eligibility';
import { useScenarioTemplates } from '@/features/scenario-templates/hooks/use-scenario-templates';
import { useDeviceGroups } from '@/features/device-groups/hooks/use-device-groups';
import type {
  ScheduleOut,
  SchedulePatch,
  ScheduleCreate
} from '../services/api';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { CronBuilder } from './cron-builder';
import { ScheduleDevicePicker } from './schedule-device-picker';
import {
  buildScheduleDeviceTarget,
  resolveScheduleDeviceMode,
  type ScheduleDeviceMode
} from './schedule-device-target';
import { VariableEditor } from '@/components/variable-editor';
import { FlowEditor } from '@/features/campaigns/components/flow-editor/flow-editor';
import { canPersistScenario } from '@/features/campaigns/components/flow-editor/nested-step-edit';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { validateScenarioStepsForApi } from '@/features/campaigns/utils/validate-scenario-steps-for-api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import {
  Dialog,
  DialogContent,
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
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import {
  ScheduleCalendarPreview,
  type ScheduleCalendarPreviewItem
} from './schedule-calendar-preview';

type Mode = 'create' | 'edit';
type ScheduleTargetType = 'campaign' | 'template' | 'org_scenario' | 'fleet';

type TargetOption = {
  value: string;
  label: string;
};

const TARGET_PICKER_PAGE_SIZE = 8;
const SCHEDULE_FORM_COPY_FALLBACKS = {
  deviceModeLabel: {
    en: 'Target devices',
    vi: 'Thiết bị chạy'
  },
  deviceModeAll: {
    en: 'All ready devices',
    vi: 'Tất cả thiết bị sẵn sàng'
  },
  deviceModeGroup: {
    en: 'By group',
    vi: 'Theo nhóm'
  },
  deviceModeDevices: {
    en: 'Pick devices',
    vi: 'Chọn thiết bị cụ thể'
  }
} as const;

type ScheduleFormCopyKey = keyof typeof SCHEDULE_FORM_COPY_FALLBACKS;

function translateScheduleFormCopy(
  t: (key: string) => string,
  locale: string,
  key: ScheduleFormCopyKey
) {
  try {
    const translated = t(key);
    if (
      translated &&
      translated !== key &&
      translated !== `schedulesFeature.form.${key}`
    ) {
      return translated;
    }
  } catch {
    // Use a readable fallback if the runtime message bundle is stale.
  }

  return SCHEDULE_FORM_COPY_FALLBACKS[key][locale === 'en' ? 'en' : 'vi'];
}

function normalizeTargetText(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .toLowerCase();
}

function PaginatedTargetPicker({
  value,
  onValueChange,
  options,
  placeholder,
  searchPlaceholder,
  noResultsText,
  pageStatusText,
  previousText,
  nextText
}: {
  value: string | null;
  onValueChange: (value: string | null) => void;
  options: TargetOption[];
  placeholder: string;
  searchPlaceholder: string;
  noResultsText: string;
  pageStatusText: (page: number, total: number) => string;
  previousText: string;
  nextText: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);

  useEffect(() => {
    setPage(0);
  }, [options, query]);

  const filteredOptions = useMemo(() => {
    const needle = normalizeTargetText(query.trim());
    if (!needle) return options;
    return options.filter((option) => {
      const haystack = `${option.label} ${option.value}`;
      return normalizeTargetText(haystack).includes(needle);
    });
  }, [options, query]);

  const pageCount = Math.max(
    1,
    Math.ceil(filteredOptions.length / TARGET_PICKER_PAGE_SIZE)
  );
  const currentPage = Math.min(page, pageCount - 1);
  const visibleOptions = filteredOptions.slice(
    currentPage * TARGET_PICKER_PAGE_SIZE,
    currentPage * TARGET_PICKER_PAGE_SIZE + TARGET_PICKER_PAGE_SIZE
  );
  const selected = options.find((option) => option.value === value);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant='outline'
          role='combobox'
          aria-expanded={open}
          className='w-full justify-between'
        >
          <span className='truncate'>{selected?.label ?? placeholder}</span>
          <ChevronsUpDown className='size-4 opacity-50' />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align='start'
        className='z-[10001] w-[var(--radix-popover-trigger-width)] p-2'
      >
        <div className='relative'>
          <Search className='pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground' />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={searchPlaceholder}
            className='h-8 pl-8'
          />
        </div>
        <div className='mt-2 max-h-64 overflow-y-auto'>
          {visibleOptions.length ? (
            visibleOptions.map((option) => (
              <button
                key={option.value}
                type='button'
                className={cn(
                  'flex h-9 w-full items-center gap-2 rounded-sm px-2 text-left text-sm hover:bg-accent hover:text-accent-foreground',
                  value === option.value && 'bg-accent/70'
                )}
                onClick={() => {
                  onValueChange(option.value);
                  setOpen(false);
                }}
              >
                <span className='min-w-0 flex-1 truncate'>{option.label}</span>
                {value === option.value && <Check className='size-4' />}
              </button>
            ))
          ) : (
            <p className='px-2 py-6 text-center text-sm text-muted-foreground'>
              {noResultsText}
            </p>
          )}
        </div>
        {pageCount > 1 && (
          <div className='mt-2 flex items-center justify-between border-t pt-2 text-xs text-muted-foreground'>
            <Button
              type='button'
              variant='ghost'
              size='icon'
              className='size-7'
              aria-label={previousText}
              disabled={currentPage === 0}
              onClick={() => setPage((prev) => Math.max(0, prev - 1))}
            >
              <ChevronLeft className='size-4' />
            </Button>
            <span>{pageStatusText(currentPage + 1, pageCount)}</span>
            <Button
              type='button'
              variant='ghost'
              size='icon'
              className='size-7'
              aria-label={nextText}
              disabled={currentPage >= pageCount - 1}
              onClick={() =>
                setPage((prev) => Math.min(pageCount - 1, prev + 1))
              }
            >
              <ChevronRight className='size-4' />
            </Button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

export function ScheduleFormDialog({
  open,
  onOpenChange,
  mode,
  schedule
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: Mode;
  schedule?: ScheduleOut | null;
}) {
  const [childStepEditorOpen, setChildStepEditorOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [targetType, setTargetType] = useState<ScheduleTargetType>('campaign');
  const [targetId, setTargetId] = useState<string | null>(null);

  const [cronExpression, setCronExpression] = useState('*/30 * * * *');
  const [timezone, setTimezone] = useState('Asia/Ho_Chi_Minh');

  const [deviceMode, setDeviceMode] = useState<ScheduleDeviceMode>('all');
  const [deviceGroupId, setDeviceGroupId] = useState<string | null>(null);
  const [deviceSerials, setDeviceSerials] = useState<string[]>([]);

  const [filterState, setFilterState] = useState('READY');
  const [filterModel, setFilterModel] = useState<string>('');
  const [maxDevices, setMaxDevices] = useState<number | null>(null);

  const [randomDelayMin, setRandomDelayMin] = useState(0);
  const [randomDelayMax, setRandomDelayMax] = useState(0);
  const [staggerDevices, setStaggerDevices] = useState(false);
  const [staggerIntervalSeconds, setStaggerIntervalSeconds] = useState(60);

  const [isEnabled, setIsEnabled] = useState(true);

  const [inlineSteps, setInlineSteps] = useState<FlowStep[]>([]);
  const [inlineVariables, setInlineVariables] = useState<Record<string, any>>(
    {}
  );

  const { data: campaigns } = useCampaigns();
  const { data: templates } = useScenarioTemplates();
  const { data: orgScenarios } = useOrgScenarios();
  const { data: groups } = useDeviceGroups();

  const createMutation = useCreateSchedule();
  const updateMutation = useUpdateSchedule();

  const t = useTranslations('schedulesFeature.form');
  const locale = useLocale();

  const title =
    mode === 'create'
      ? t('titleCreate')
      : t('titleEdit', { name: schedule?.name ?? '' });
  const deviceModeLabel = translateScheduleFormCopy(
    t,
    locale,
    'deviceModeLabel'
  );
  const deviceModeOptions = [
    {
      value: 'all',
      label: translateScheduleFormCopy(t, locale, 'deviceModeAll')
    },
    {
      value: 'group',
      label: translateScheduleFormCopy(t, locale, 'deviceModeGroup')
    },
    {
      value: 'devices',
      label: translateScheduleFormCopy(t, locale, 'deviceModeDevices')
    }
  ] satisfies { value: ScheduleDeviceMode; label: string }[];

  const previewTargetLabel = useMemo(() => {
    if (targetType === 'campaign') {
      return (
        (campaigns ?? []).find((campaign) => campaign.id === targetId)?.name ??
        t('targetCampaign')
      );
    }
    if (targetType === 'template') {
      return (
        (templates ?? []).find((template) => template.id === targetId)?.name ??
        t('targetTemplate')
      );
    }
    if (targetType === 'org_scenario') {
      return (
        (orgScenarios ?? []).find((scenario) => scenario.id === targetId)
          ?.name ?? t('targetOrgScenario')
      );
    }
    return t('targetFleet');
  }, [campaigns, orgScenarios, targetId, targetType, templates, t]);

  const targetOptions = useMemo(() => {
    if (targetType === 'campaign') {
      return (campaigns ?? []).map((campaign) => ({
        value: campaign.id,
        label: campaign.name
      }));
    }
    if (targetType === 'template') {
      return (templates ?? []).map((template) => ({
        value: template.id,
        label: template.name
      }));
    }
    if (targetType === 'org_scenario') {
      return (orgScenarios ?? [])
        .filter(
          (scenario) =>
            scenario.is_runnable &&
            isOrgScenarioVisibleInCampaignPicker(scenario)
        )
        .map((scenario) => ({
          value: scenario.id,
          label: scenario.name
        }));
    }
    return [];
  }, [campaigns, orgScenarios, targetType, templates]);

  const previewSchedule = useMemo<ScheduleCalendarPreviewItem>(
    () => ({
      id: schedule?.id ?? 'draft',
      name: name.trim() || t('namePlaceholder'),
      cronExpression: cronExpression.trim() || '*/30 * * * *',
      timezone,
      targetLabel: previewTargetLabel,
      isEnabled
    }),
    [
      cronExpression,
      isEnabled,
      name,
      previewTargetLabel,
      schedule?.id,
      t,
      timezone
    ]
  );

  useEffect(() => {
    if (!open) return;
    if (mode === 'create') {
      setName('');
      setDescription('');
      setTargetType('campaign');
      setTargetId(null);
      setCronExpression('*/30 * * * *');
      setTimezone('Asia/Ho_Chi_Minh');
      setDeviceMode('all');
      setDeviceGroupId(null);
      setDeviceSerials([]);
      setFilterState('READY');
      setFilterModel('');
      setMaxDevices(null);
      setRandomDelayMin(0);
      setRandomDelayMax(0);
      setStaggerDevices(false);
      setStaggerIntervalSeconds(60);
      setIsEnabled(true);
      setInlineSteps([]);
      setInlineVariables({});
      return;
    }

    const s = schedule;
    if (!s) return;
    setName(s.name ?? '');
    setDescription(s.description ?? '');
    setTargetType(s.target_type as any);
    setTargetId(s.target_id ?? null);
    setCronExpression(s.cron_expression ?? '*/30 * * * *');
    setTimezone(s.timezone ?? 'Asia/Ho_Chi_Minh');
    setDeviceMode(resolveScheduleDeviceMode(s));
    setDeviceGroupId(s.device_group_id ?? null);
    setDeviceSerials(s.device_serials ?? []);
    setFilterState(s.filter_state ?? 'READY');
    setFilterModel(s.filter_model ?? '');
    setMaxDevices(s.max_devices ?? null);
    setRandomDelayMin((s as any).random_delay_min ?? 0);
    setRandomDelayMax((s as any).random_delay_max ?? 0);
    setStaggerDevices(Boolean((s as any).stagger_devices));
    setStaggerIntervalSeconds((s as any).stagger_interval_seconds ?? 60);
    setIsEnabled(Boolean((s as any).is_enabled));
    setInlineSteps(
      Array.isArray(s.inline_steps) ? (s.inline_steps as any as FlowStep[]) : []
    );
    setInlineVariables(s.inline_variables ?? {});
  }, [open, mode, schedule]);

  const onSubmit = async () => {
    if (!canPersistScenario(childStepEditorOpen)) {
      toast.info(
        'Đóng trình chỉnh sửa bước để áp dụng thay đổi trước khi lưu.'
      );
      return;
    }
    if (!name.trim()) {
      toast.error(t('errorNameRequired'));
      return;
    }
    const cron = cronExpression.trim();
    const tz = timezone.trim();
    if (!cron) {
      toast.error(t('errorCronRequired'));
      return;
    }
    if (
      (targetType === 'campaign' ||
        targetType === 'template' ||
        targetType === 'org_scenario') &&
      !targetId
    ) {
      toast.error(t('errorTargetIdRequired', { targetType }));
      return;
    }
    if (targetType === 'fleet') {
      if (!inlineSteps.length) {
        toast.error(t('errorInlineStepsRequired'));
        return;
      }
      const check = validateScenarioStepsForApi(inlineSteps);
      if (!check.ok) {
        toast.error(check.message);
        return;
      }
    }

    if (randomDelayMax > 0 && randomDelayMax < randomDelayMin) {
      toast.error(t('errorRandomDelay'));
      return;
    }

    if (deviceMode === 'devices' && !deviceSerials.length) {
      toast.error(t('errorDevicesRequired'));
      return;
    }
    const deviceTarget = buildScheduleDeviceTarget(
      deviceMode,
      deviceGroupId,
      deviceSerials
    );

    if (mode === 'create') {
      const data: ScheduleCreate = {
        name: name.trim(),
        description: description ?? '',
        target_type: targetType,
        target_id: targetType === 'fleet' ? null : targetId,
        cron_expression: cron,
        timezone: tz ? tz : undefined,
        ...deviceTarget,
        filter_state: filterState || 'READY',
        filter_model: filterModel?.trim() ? filterModel.trim() : undefined,
        max_devices: maxDevices ?? undefined,
        random_delay_min: randomDelayMin ?? 0,
        random_delay_max: randomDelayMax ?? 0,
        stagger_devices: staggerDevices,
        stagger_interval_seconds: staggerIntervalSeconds,
        is_enabled: isEnabled
      };

      if (targetType === 'fleet') {
        data.inline_steps = inlineSteps as any;
        data.inline_variables = inlineVariables ?? {};
      }

      createMutation.mutate(data, {
        onSuccess: () => {
          toast.success(t('createSuccess'));
          onOpenChange(false);
        },
        onError: (err: unknown) =>
          toast.error(formatFarmApiError(err, t('createFailed')))
      });
      return;
    }

    const s = schedule;
    if (!s?.id) return;

    const patch: SchedulePatch = {
      name: name.trim(),
      description: description ?? '',
      target_type: targetType,
      target_id: targetType === 'fleet' ? null : targetId,
      cron_expression: cron,
      timezone: tz ? tz : undefined,
      ...deviceTarget,
      filter_state: filterState || 'READY',
      filter_model: filterModel?.trim() ? filterModel.trim() : undefined,
      max_devices: maxDevices ?? undefined,
      random_delay_min: randomDelayMin ?? 0,
      random_delay_max: randomDelayMax ?? 0,
      stagger_devices: staggerDevices,
      stagger_interval_seconds: staggerIntervalSeconds,
      is_enabled: isEnabled
    };

    if (targetType === 'fleet') {
      patch.inline_steps = inlineSteps as any;
      patch.inline_variables = inlineVariables ?? {};
    } else {
      patch.inline_steps = undefined;
      patch.inline_variables = undefined;
    }

    updateMutation.mutate(
      { scheduleId: s.id, data: patch },
      {
        onSuccess: () => {
          toast.success(t('updateSuccess'));
          onOpenChange(false);
        },
        onError: (err: unknown) =>
          toast.error(formatFarmApiError(err, t('updateFailed')))
      }
    );
  };

  const isPending =
    mode === 'create' ? createMutation.isPending : updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='z-[1000] flex max-h-[92vh] w-[calc(100vw-2rem)] flex-col overflow-hidden p-0 sm:max-w-[760px] xl:max-w-[1180px]'>
        <DialogHeader className='shrink-0 border-b bg-muted/25 px-5 py-4'>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <div className='flex-1 overflow-y-auto bg-muted/15 p-4 sm:p-5'>
          <div className='grid gap-5 xl:grid-cols-[minmax(34rem,1fr)_34rem]'>
            <div className='space-y-5'>
              {/* ── Thông tin cơ bản ── */}
              <div className='space-y-4 rounded-lg border bg-background p-4 shadow-sm'>
                <div className='space-y-1'>
                  <Label>{t('nameLabel')}</Label>
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t('namePlaceholder')}
                  />
                </div>
                <div className='space-y-1'>
                  <Label>{t('descriptionLabel')}</Label>
                  <Textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={2}
                    placeholder={t('optional')}
                  />
                </div>
                <div className='flex items-center gap-3'>
                  <Switch
                    checked={isEnabled}
                    onCheckedChange={setIsEnabled}
                    id='schedule-enabled'
                  />
                  <label
                    htmlFor='schedule-enabled'
                    className='cursor-pointer select-none text-sm'
                  >
                    {isEnabled ? t('enabledOn') : t('enabledOff')}
                  </label>
                </div>
              </div>

              {/* ── Mục tiêu ── */}
              <div className='space-y-3 rounded-lg border bg-background p-4 shadow-sm'>
                <p className='text-xs font-semibold uppercase tracking-wide text-muted-foreground'>
                  {t('targetTypeLabel')}
                </p>
                {targetType === 'fleet' && mode === 'edit' ? (
                  <p className='text-sm text-muted-foreground'>
                    {t('targetFleet')}
                  </p>
                ) : (
                  <Select
                    value={targetType === 'fleet' ? 'campaign' : targetType}
                    onValueChange={(v) => {
                      const next = v as
                        | 'campaign'
                        | 'template'
                        | 'org_scenario';
                      setTargetType(next);
                      setTargetId(null);
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className='z-[10001]'>
                      <SelectItem value='campaign'>
                        {t('targetCampaign')}
                      </SelectItem>
                      <SelectItem value='template'>
                        {t('targetTemplate')}
                      </SelectItem>
                      <SelectItem value='org_scenario'>
                        {t('targetOrgScenario')}
                      </SelectItem>
                    </SelectContent>
                  </Select>
                )}

                {(targetType === 'campaign' ||
                  targetType === 'template' ||
                  targetType === 'org_scenario') && (
                  <div className='space-y-1'>
                    <Label>{t('targetLabel')}</Label>
                    <PaginatedTargetPicker
                      key={targetType}
                      value={targetId}
                      onValueChange={setTargetId}
                      options={targetOptions}
                      placeholder={
                        targetType === 'campaign'
                          ? t('pickCampaign')
                          : targetType === 'template'
                            ? t('pickTemplate')
                            : t('pickOrgScenario')
                      }
                      searchPlaceholder={t('targetSearchPlaceholder')}
                      noResultsText={t('targetNoResults')}
                      pageStatusText={(page, total) =>
                        t('targetPageStatus', { page, total })
                      }
                      previousText={t('targetPreviousPage')}
                      nextText={t('targetNextPage')}
                    />
                  </div>
                )}

                {targetType === 'fleet' && (
                  <div className='space-y-2'>
                    <Label>
                      {t('inlineStepsLabel', { count: inlineSteps.length })}
                    </Label>
                    <FlowEditor
                      steps={inlineSteps}
                      onChange={setInlineSteps}
                      compact
                      maxHeight='min(320px,40vh)'
                      onChildStepEditorOpenChange={setChildStepEditorOpen}
                    />
                  </div>
                )}

                {targetType === 'fleet' && (
                  <details className='group'>
                    <summary className='flex cursor-pointer items-center gap-2 text-sm font-medium'>
                      {t('inlineVariablesSummary')}
                      {Object.keys(inlineVariables ?? {}).length > 0 && (
                        <span className='text-xs text-muted-foreground'>
                          ({Object.keys(inlineVariables).length})
                        </span>
                      )}
                    </summary>
                    <div className='pt-2'>
                      <VariableEditor
                        variables={inlineVariables}
                        onChange={setInlineVariables}
                      />
                      <p className='mt-1 text-[10px] text-muted-foreground'>
                        {t('inlineVariablesHintPrefix')}{' '}
                        <code className='rounded bg-muted px-1 py-0.5'>
                          {'${__DEVICE_SERIAL__}'}
                        </code>
                        {t('inlineVariablesHintSuffix')}
                      </p>
                    </div>
                  </details>
                )}
              </div>

              {/* ── Lịch cron ── */}
              <div className='rounded-lg border bg-background p-4 shadow-sm'>
                <CronBuilder
                  key={`${mode}-${schedule?.id ?? 'new'}-${open ? 'open' : 'closed'}`}
                  value={cronExpression}
                  onChange={setCronExpression}
                />
              </div>

              {/* ── Nhóm thiết bị ── */}
              <div className='space-y-4 rounded-lg border bg-background p-4 shadow-sm'>
                <div className='grid grid-cols-1 gap-4 sm:grid-cols-2'>
                  <div className='space-y-2'>
                    <Label>{deviceModeLabel}</Label>
                    <Select
                      value={deviceMode}
                      onValueChange={(value) =>
                        setDeviceMode(value as ScheduleDeviceMode)
                      }
                    >
                      <SelectTrigger className='w-full'>
                        <SelectValue placeholder={deviceModeLabel} />
                      </SelectTrigger>
                      <SelectContent className='z-[10001]'>
                        {deviceModeOptions.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>

                    {deviceMode === 'group' && (
                      <Select
                        value={deviceGroupId ?? '_none'}
                        onValueChange={(v) =>
                          setDeviceGroupId(v === '_none' ? null : v)
                        }
                      >
                        <SelectTrigger>
                          <SelectValue placeholder={t('deviceGroupLabel')} />
                        </SelectTrigger>
                        <SelectContent className='z-[10001]'>
                          <SelectItem value='_none'>
                            {t('allReadyDevices')}
                          </SelectItem>
                          {(groups ?? []).map((g) => (
                            <SelectItem key={g.id} value={g.id}>
                              {g.name} ({g.device_count})
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}

                    {deviceMode === 'devices' && (
                      <ScheduleDevicePicker
                        value={deviceSerials}
                        onChange={setDeviceSerials}
                      />
                    )}
                  </div>
                  <div className='space-y-1'>
                    <Label>{t('timezoneLabel')}</Label>
                    <Input
                      value={timezone}
                      onChange={(e) => setTimezone(e.target.value)}
                      placeholder={t('timezonePlaceholder')}
                    />
                  </div>
                </div>

                {/* ── Lọc thiết bị ── */}
                <div className='grid grid-cols-1 gap-4 sm:grid-cols-3'>
                  <div className='space-y-1'>
                    <Label>{t('filterStateLabel')}</Label>
                    <Input
                      value={filterState}
                      onChange={(e) => setFilterState(e.target.value)}
                      placeholder={t('filterStatePlaceholder')}
                    />
                  </div>
                  <div className='space-y-1'>
                    <Label>{t('filterModelLabel')}</Label>
                    <Input
                      value={filterModel}
                      onChange={(e) => setFilterModel(e.target.value)}
                      placeholder={t('filterModelPlaceholder')}
                    />
                  </div>
                  <div className='space-y-1'>
                    <Label>{t('maxDevicesLabel')}</Label>
                    <Input
                      type='number'
                      value={maxDevices ?? ''}
                      onChange={(e) => {
                        const v = e.target.value;
                        setMaxDevices(v === '' ? null : Math.max(1, Number(v)));
                      }}
                      placeholder={t('optional')}
                    />
                  </div>
                </div>
              </div>

              {/* ── Tuỳ chọn thời gian ── */}
              <div className='space-y-4 rounded-lg border bg-background p-4 shadow-sm'>
                <p className='text-xs font-semibold uppercase tracking-wide text-muted-foreground'>
                  {t('staggerDevicesLabel')}
                </p>
                <div className='grid grid-cols-2 gap-4'>
                  <div className='space-y-1'>
                    <Label>{t('randomDelayMinLabel')}</Label>
                    <Input
                      type='number'
                      min={0}
                      value={randomDelayMin}
                      onChange={(e) =>
                        setRandomDelayMin(
                          Math.max(0, Number(e.target.value) || 0)
                        )
                      }
                    />
                  </div>
                  <div className='space-y-1'>
                    <Label>{t('randomDelayMaxLabel')}</Label>
                    <Input
                      type='number'
                      min={0}
                      value={randomDelayMax}
                      onChange={(e) =>
                        setRandomDelayMax(
                          Math.max(0, Number(e.target.value) || 0)
                        )
                      }
                    />
                  </div>
                </div>

                <div className='flex items-center gap-3'>
                  <Switch
                    checked={staggerDevices}
                    onCheckedChange={setStaggerDevices}
                    id='stagger-toggle'
                  />
                  <div>
                    <label
                      htmlFor='stagger-toggle'
                      className='block cursor-pointer select-none text-sm font-medium'
                    >
                      {t('staggerDevicesLabel')}
                    </label>
                    <p className='text-[11px] text-muted-foreground'>
                      {t('staggerHint')}
                    </p>
                  </div>
                </div>

                {staggerDevices && (
                  <div className='space-y-1'>
                    <Label>{t('staggerIntervalSecondsLabel')}</Label>
                    <Input
                      type='number'
                      min={1}
                      max={3600}
                      value={staggerIntervalSeconds}
                      onChange={(e) =>
                        setStaggerIntervalSeconds(
                          Math.max(
                            1,
                            Math.min(3600, Number(e.target.value) || 60)
                          )
                        )
                      }
                    />
                  </div>
                )}
              </div>

              {(createMutation.error || updateMutation.error) && (
                <p className='text-xs text-destructive'>
                  {formatFarmApiError(
                    mode === 'create'
                      ? createMutation.error
                      : updateMutation.error,
                    mode === 'create' ? t('createFailed') : t('updateFailed')
                  )}
                </p>
              )}
            </div>

            <div className='xl:sticky xl:top-0 xl:self-start'>
              <ScheduleCalendarPreview
                schedules={[previewSchedule]}
                compact
                className='overflow-hidden shadow-sm'
              />
            </div>
          </div>
        </div>

        {/* ── Footer ── */}
        <div className='flex shrink-0 items-center justify-end gap-2 border-t bg-background px-5 py-4'>
          <Button
            size='sm'
            variant='outline'
            onClick={() => onOpenChange(false)}
            disabled={isPending}
          >
            {t('cancel')}
          </Button>
          <Button
            size='sm'
            onClick={() => void onSubmit()}
            disabled={isPending}
          >
            {isPending
              ? t('saving')
              : mode === 'create'
                ? t('createCta')
                : t('saveCta')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
