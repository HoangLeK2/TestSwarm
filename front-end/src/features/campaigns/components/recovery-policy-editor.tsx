'use client';

import { useMemo } from 'react';
import { Edit3, Plus, Trash2, Wrench } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { ROUTES } from '@/config/routes';
import { useRouter } from '@/i18n/navigation';
import { cn } from '@/lib/utils';
import { normalizeInternalAppPath } from '@/lib/i18n-path';
import { CreateOrgScenarioDialog } from '@/features/org-scenarios/components/create-scenario-dialog';
import { useOrgScenarios } from '@/features/org-scenarios/hooks/use-org-scenarios';
import { isOrgScenarioVisibleInCampaignPicker } from '@/features/org-scenarios/lib/campaign-scenario-eligibility';
import type { RecoveryOutcome, RecoveryPolicy, RecoveryRule } from '../types';
import {
  createDefaultRecoveryRule,
  normalizeRecoveryPolicyForEditor,
  normalizeRecoveryRuleForEditor,
  RECOVERY_EDITOR_OUTCOMES
} from '../lib/recovery-policy-editor-model';

const fieldLabelClass = 'text-xs font-medium text-muted-foreground';
const ruleGridClass =
  'grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_5.5rem] sm:items-end';

export function RecoveryPolicyEditor({
  value,
  onChange,
  disabled = false,
  recordCampaignId = null,
  recordDeviceSerial = null,
  onBeforeRecord,
  variant = 'default',
  scenarioFilter = 'all'
}: {
  value?: RecoveryPolicy | null;
  onChange: (value: RecoveryPolicy) => void;
  disabled?: boolean;
  recordCampaignId?: string | null;
  recordDeviceSerial?: string | null;
  onBeforeRecord?: (value: RecoveryPolicy) => Promise<void> | void;
  variant?: 'default' | 'embedded';
  scenarioFilter?: 'all' | 'recovery';
}) {
  const t = useTranslations('campaignsFeature.recoveryPolicy');
  const router = useRouter();
  const { data: orgScenarios } = useOrgScenarios();

  const scenarios = useMemo(
    () =>
      (orgScenarios ?? [])
        .filter((scenario) => isOrgScenarioVisibleInCampaignPicker(scenario))
        .filter(
          (scenario) =>
            scenarioFilter !== 'recovery' ||
            scenario.is_recovery_scenario === true ||
            (scenario.recovery_usage_count ?? 0) > 0
        )
        .filter((scenario) => scenario.kind !== 'graph'),
    [orgScenarios, scenarioFilter]
  );

  const policy = normalizeRecoveryPolicyForEditor(value);
  const rules = policy.rules ?? [];
  const defaultScenarioId = scenarios[0]?.id ?? null;
  const canRecordOnDevice = Boolean(recordCampaignId);
  const embedded = variant === 'embedded';

  const emit = (next: RecoveryPolicy) => {
    const normalized = normalizeRecoveryPolicyForEditor(next);
    onChange({
      enabled: Boolean(normalized.enabled),
      max_total_attempts: normalized.max_total_attempts,
      max_attempts_per_step: normalized.max_attempts_per_step,
      rules: (normalized.rules ?? []).map(normalizeRecoveryRuleForEditor)
    });
  };

  const setEnabled = (enabled: boolean) => {
    emit({
      enabled,
      max_total_attempts: policy.max_total_attempts,
      max_attempts_per_step: policy.max_attempts_per_step,
      rules:
        rules.length > 0
          ? rules
          : [createDefaultRecoveryRule(defaultScenarioId)]
    });
  };

  const updateRule = (index: number, patch: Partial<RecoveryRule>) => {
    emit({
      enabled: policy.enabled,
      max_total_attempts: policy.max_total_attempts,
      max_attempts_per_step: policy.max_attempts_per_step,
      rules: rules.map((rule, i) =>
        i === index
          ? normalizeRecoveryRuleForEditor({ ...rule, ...patch })
          : rule
      )
    });
  };

  const policyWithRulePatch = (
    index: number,
    patch: Partial<RecoveryRule>
  ): RecoveryPolicy => ({
    enabled: policy.enabled,
    max_total_attempts: policy.max_total_attempts,
    max_attempts_per_step: policy.max_attempts_per_step,
    rules: rules.map((rule, i) =>
      i === index ? normalizeRecoveryRuleForEditor({ ...rule, ...patch }) : rule
    )
  });

  const addRule = () => {
    emit({
      enabled: true,
      max_total_attempts: policy.max_total_attempts,
      max_attempts_per_step: policy.max_attempts_per_step,
      rules: [...rules, createDefaultRecoveryRule(defaultScenarioId)]
    });
  };

  const removeRule = (index: number) => {
    const nextRules = rules.filter((_, i) => i !== index);
    emit({
      enabled: nextRules.length > 0 && Boolean(policy.enabled),
      max_total_attempts: policy.max_total_attempts,
      max_attempts_per_step: policy.max_attempts_per_step,
      rules: nextRules
    });
  };

  const updatePolicyBudget = (patch: Partial<RecoveryPolicy>) => {
    emit({
      ...policy,
      ...patch,
      rules
    });
  };

  const currentReturnTo = () => {
    if (typeof window === 'undefined') return ROUTES.CAMPAIGNS.ROOT;
    return normalizeInternalAppPath(
      `${window.location.pathname}${window.location.search}`,
      ROUTES.CAMPAIGNS.ROOT
    );
  };

  const openRecordForScenario = async (
    scenarioId: string,
    nextPolicy: RecoveryPolicy = policy
  ) => {
    await onBeforeRecord?.(nextPolicy);
    router.push(
      ROUTES.DEVICES.CONTROL_RECORD_EDIT_ORG_SCENARIO(scenarioId, {
        returnTo: currentReturnTo(),
        campaignId: recordCampaignId || undefined,
        serial: recordDeviceSerial || undefined
      })
    );
  };

  return (
    <div
      className={cn(
        'space-y-3',
        !embedded && 'rounded-lg border border-border/60 bg-muted/10 p-4',
        disabled && 'pointer-events-none opacity-60'
      )}
    >
      {embedded ? (
        <div className='flex items-center justify-between gap-4 rounded-lg border border-border/60 bg-muted/30 px-4 py-3'>
          <div className='min-w-0'>
            <p className='text-sm font-medium leading-none'>{t('title')}</p>
            <p className='mt-1 text-xs text-muted-foreground'>{t('hint')}</p>
          </div>
          <Switch
            checked={Boolean(policy.enabled)}
            onCheckedChange={setEnabled}
            disabled={disabled}
            className='shrink-0'
          />
        </div>
      ) : (
        <div className='flex items-start justify-between gap-4'>
          <div className='flex min-w-0 items-start gap-3'>
            <div className='mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 text-amber-700 dark:text-amber-300'>
              <Wrench className='size-4' aria-hidden />
            </div>
            <div className='min-w-0 space-y-1'>
              <Label className='text-sm font-medium leading-none'>
                {t('title')}
              </Label>
              <p className='text-xs leading-relaxed text-muted-foreground'>
                {t('hint')}
              </p>
            </div>
          </div>
          <Switch
            checked={Boolean(policy.enabled)}
            onCheckedChange={setEnabled}
            disabled={disabled}
            className='shrink-0'
          />
        </div>
      )}

      {policy.enabled ? (
        <div className='space-y-3'>
          {!canRecordOnDevice ? (
            <p className='bg-amber-500/8 rounded-md border border-amber-500/25 px-3 py-2 text-xs leading-relaxed text-amber-900 dark:text-amber-100'>
              {t('recordRequiresCampaign')}
            </p>
          ) : null}

          {!scenarios.length ? (
            <p className='bg-amber-500/8 rounded-md border border-amber-500/25 px-3 py-2 text-xs leading-relaxed text-amber-900 dark:text-amber-100'>
              {t('noRunnableScenarios')}
            </p>
          ) : null}

          <div className='grid grid-cols-1 gap-3 sm:grid-cols-2'>
            <div className='space-y-1.5'>
              <Label className={fieldLabelClass}>
                {t('maxTotalAttemptsLabel')}
              </Label>
              <Input
                type='number'
                min={0}
                max={10000}
                value={policy.max_total_attempts ?? 100}
                disabled={disabled}
                onChange={(event) =>
                  updatePolicyBudget({
                    max_total_attempts: Number(event.target.value || 0)
                  })
                }
                className='h-9 text-sm tabular-nums'
              />
            </div>
            <div className='space-y-1.5'>
              <Label className={fieldLabelClass}>
                {t('maxStepAttemptsLabel')}
              </Label>
              <Input
                type='number'
                min={0}
                max={20}
                value={policy.max_attempts_per_step ?? 2}
                disabled={disabled}
                onChange={(event) =>
                  updatePolicyBudget({
                    max_attempts_per_step: Number(event.target.value || 0)
                  })
                }
                className='h-9 text-sm tabular-nums'
              />
            </div>
            <p className='text-[11px] leading-relaxed text-muted-foreground sm:col-span-2'>
              {t('budgetHint')}
            </p>
          </div>

          {rules.map((rule, index) => (
            <div
              key={index}
              className={cn(
                'rounded-lg border border-border/60 bg-background',
                index > 0 && 'mt-1'
              )}
            >
              {rules.length > 1 ? (
                <div className='flex items-center justify-between border-b px-4 py-2'>
                  <span className='text-xs font-medium text-muted-foreground'>
                    #{index + 1}
                  </span>
                  <Button
                    type='button'
                    variant='ghost'
                    size='icon'
                    className='size-7 text-muted-foreground hover:text-destructive'
                    disabled={disabled}
                    onClick={() => removeRule(index)}
                    aria-label='Remove rule'
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              ) : null}

              <div className='p-4'>
                <div className={ruleGridClass}>
                  <div className='min-w-0 space-y-1.5'>
                    <Label className={fieldLabelClass}>
                      {t('scenarioLabel')}
                    </Label>
                    <Select
                      value={rule.scenario_id || '_none'}
                      disabled={disabled}
                      onValueChange={(scenarioId) =>
                        updateRule(index, {
                          scenario_id:
                            scenarioId === '_none' ? null : scenarioId
                        })
                      }
                    >
                      <SelectTrigger className='h-9 w-full text-sm'>
                        <SelectValue placeholder={t('scenarioNone')} />
                      </SelectTrigger>
                      <SelectContent className='z-[10001]'>
                        <SelectItem value='_none'>
                          {t('scenarioNone')}
                        </SelectItem>
                        {scenarios.map((scenario) => (
                          <SelectItem key={scenario.id} value={scenario.id}>
                            {scenario.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className='min-w-0 space-y-1.5'>
                    <Label className={fieldLabelClass}>
                      {t('outcomeLabel')}
                    </Label>
                    <Select
                      value={rule.outcome ?? 'retry_step'}
                      disabled={disabled}
                      onValueChange={(outcome) =>
                        updateRule(index, {
                          outcome: outcome as RecoveryOutcome
                        })
                      }
                    >
                      <SelectTrigger className='h-9 w-full text-sm'>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className='z-[10001]'>
                        {RECOVERY_EDITOR_OUTCOMES.map((outcome) => (
                          <SelectItem key={outcome} value={outcome}>
                            {t(`outcome.${outcome}`)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className='space-y-1.5 sm:col-start-3'>
                    <Label className={fieldLabelClass}>
                      {t('attemptsLabel')}
                    </Label>
                    <Input
                      type='number'
                      min={1}
                      max={10}
                      value={rule.max_attempts ?? 1}
                      disabled={disabled}
                      onChange={(event) =>
                        updateRule(index, {
                          max_attempts: Number(event.target.value || 1)
                        })
                      }
                      className='h-9 w-full text-center text-sm tabular-nums'
                    />
                  </div>

                  <p className='text-[11px] leading-relaxed text-muted-foreground sm:col-span-3'>
                    {t('scenarioHint')}
                  </p>

                  <Button
                    type='button'
                    variant='secondary'
                    size='sm'
                    className='h-9 w-full gap-1.5 text-xs'
                    disabled={
                      disabled || !rule.scenario_id || !canRecordOnDevice
                    }
                    onClick={() =>
                      void openRecordForScenario(rule.scenario_id!)
                    }
                  >
                    <Edit3 size={14} className='shrink-0' />
                    <span className='truncate'>{t('editScenario')}</span>
                  </Button>

                  <div className='w-full min-w-0'>
                    <CreateOrgScenarioDialog
                      onCreated={(created) => {
                        const nextPolicy = policyWithRulePatch(index, {
                          scenario_id: created.id,
                          scenario_name: created.name
                        });
                        onChange(nextPolicy);
                        void openRecordForScenario(created.id, nextPolicy);
                      }}
                      trigger={
                        <Button
                          type='button'
                          variant='outline'
                          size='sm'
                          className='h-9 w-full gap-1.5 text-xs'
                          disabled={disabled || !canRecordOnDevice}
                        >
                          <Plus size={14} className='shrink-0' />
                          <span className='truncate'>
                            {t('createScenario')}
                          </span>
                        </Button>
                      }
                    />
                  </div>
                </div>
              </div>
            </div>
          ))}

          <Button
            type='button'
            variant='ghost'
            size='sm'
            className='h-8 gap-1.5 px-2 text-xs text-muted-foreground hover:text-foreground'
            onClick={addRule}
            disabled={disabled || !scenarios.length}
          >
            <Plus size={14} />
            {t('addRule')}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
