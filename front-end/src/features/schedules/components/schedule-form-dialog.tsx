'use client';

import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';
import { useCreateSchedule, useUpdateSchedule } from '../hooks/use-schedules';
import { useCampaigns } from '@/features/campaigns/hooks/use-campaigns';
import { useScenarioTemplates } from '@/features/scenario-templates/hooks/use-scenario-templates';
import { useDeviceGroups } from '@/features/device-groups/hooks/use-device-groups';
import type {
  ScheduleOut,
  SchedulePatch,
  ScheduleCreate
} from '../services/api';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { CronBuilder } from './cron-builder';
import { VariableEditor } from '@/components/variable-editor';
import { FlowEditor } from '@/features/campaigns/components/flow-editor/flow-editor';
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

type Mode = 'create' | 'edit';

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
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [targetType, setTargetType] =
    useState<ScheduleCreate['target_type']>('campaign');
  const [targetId, setTargetId] = useState<string | null>(null);

  const [cronExpression, setCronExpression] = useState('*/30 * * * *');
  const [timezone, setTimezone] = useState('Asia/Ho_Chi_Minh');

  const [deviceGroupId, setDeviceGroupId] = useState<string | null>(null);

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
  const { data: groups } = useDeviceGroups();

  const createMutation = useCreateSchedule();
  const updateMutation = useUpdateSchedule();

  const t = useTranslations('schedulesFeature.form');

  const title =
    mode === 'create'
      ? t('titleCreate')
      : t('titleEdit', { name: schedule?.name ?? '' });

  useEffect(() => {
    if (!open) return;
    if (mode === 'create') {
      setName('');
      setDescription('');
      setTargetType('campaign');
      setTargetId(null);
      setCronExpression('*/30 * * * *');
      setTimezone('Asia/Ho_Chi_Minh');
      setDeviceGroupId(null);
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
    setDeviceGroupId(s.device_group_id ?? null);
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
    if ((targetType === 'campaign' || targetType === 'template') && !targetId) {
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

    if (mode === 'create') {
      const data: ScheduleCreate = {
        name: name.trim(),
        description: description ?? '',
        target_type: targetType,
        target_id: targetType === 'fleet' ? null : targetId,
        cron_expression: cron,
        timezone: tz ? tz : undefined,
        device_group_id: deviceGroupId ?? undefined,
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
      device_group_id: deviceGroupId ?? undefined,
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
      <DialogContent className='z-[1000] flex max-h-[90vh] max-w-2xl flex-col'>
        <DialogHeader className='shrink-0'>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <div className='flex-1 space-y-5 overflow-y-auto pr-1 pt-2'>
          {/* ── Thông tin cơ bản ── */}
          <div className='space-y-3'>
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
          <div className='space-y-3 rounded-lg border p-3'>
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
                  const next = v as 'campaign' | 'template';
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
                </SelectContent>
              </Select>
            )}

            {(targetType === 'campaign' || targetType === 'template') && (
              <div className='space-y-1'>
                <Label>{t('targetLabel')}</Label>
                {targetType === 'campaign' ? (
                  <Select
                    value={targetId ?? '_none'}
                    onValueChange={(v) => setTargetId(v === '_none' ? null : v)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={t('pickCampaign')} />
                    </SelectTrigger>
                    <SelectContent className='z-[10001]'>
                      <SelectItem value='_none'>
                        {t('selectCampaign')}
                      </SelectItem>
                      {(campaigns ?? []).map((c) => (
                        <SelectItem key={c.id} value={c.id}>
                          {c.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Select
                    value={targetId ?? '_none'}
                    onValueChange={(v) => setTargetId(v === '_none' ? null : v)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={t('pickTemplate')} />
                    </SelectTrigger>
                    <SelectContent className='z-[10001]'>
                      <SelectItem value='_none'>
                        {t('selectTemplate')}
                      </SelectItem>
                      {(templates ?? []).map((tpl) => (
                        <SelectItem key={tpl.id} value={tpl.id}>
                          {tpl.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
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
          <div className='space-y-2'>
            <CronBuilder
              value={cronExpression}
              onChange={(next) => setCronExpression(next)}
            />
          </div>

          {/* ── Nhóm thiết bị ── */}
          <div className='grid grid-cols-2 gap-4'>
            <div className='space-y-1'>
              <Label>{t('deviceGroupLabel')}</Label>
              <Select
                value={deviceGroupId ?? '_none'}
                onValueChange={(v) =>
                  setDeviceGroupId(v === '_none' ? null : v)
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('allReadyDevices')} />
                </SelectTrigger>
                <SelectContent className='z-[10001]'>
                  <SelectItem value='_none'>{t('allReadyDevices')}</SelectItem>
                  {(groups ?? []).map((g) => (
                    <SelectItem key={g.id} value={g.id}>
                      {g.name} ({g.device_count})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
          <div className='grid grid-cols-3 gap-4'>
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

          {/* ── Tuỳ chọn thời gian ── */}
          <div className='space-y-3 rounded-lg border p-3'>
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
                    setRandomDelayMin(Math.max(0, Number(e.target.value) || 0))
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
                    setRandomDelayMax(Math.max(0, Number(e.target.value) || 0))
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
                      Math.max(1, Math.min(3600, Number(e.target.value) || 60))
                    )
                  }
                />
              </div>
            )}
          </div>

          {(createMutation.error || updateMutation.error) && (
            <p className='text-xs text-destructive'>
              {formatFarmApiError(
                mode === 'create' ? createMutation.error : updateMutation.error,
                mode === 'create' ? t('createFailed') : t('updateFailed')
              )}
            </p>
          )}
        </div>

        {/* ── Footer ── */}
        <div className='flex shrink-0 items-center justify-end gap-2 border-t pt-3'>
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
