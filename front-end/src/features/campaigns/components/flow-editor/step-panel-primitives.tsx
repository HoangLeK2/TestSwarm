'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode
} from 'react';
import { useTranslations } from 'next-intl';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { useDebouncedCallback } from '@/hooks/use-debounced-callback';
import { Switch } from '@/components/ui/switch';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { FlowStep } from '../scenario-steps/types';
import { formatStepLabelForCard, getStepSummary } from './constants';
import { useCampaignFlowI18n } from './flow-i18n';
import { StepIcon } from './step-icon';
import {
  coerceStepRetryPolicy,
  formatRetryReasons,
  parseRetryReasons,
  retryPatchForEnabledState,
  withRetryField,
  type RetryBackoffStrategy
} from './step-retry-policy';

export function StepPanelField({
  label,
  children
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className='space-y-1.5'>
      <Label className='text-xs font-medium leading-none text-foreground'>
        {label}
      </Label>
      {children}
    </div>
  );
}

/** @deprecated Use StepPanelField — kept for minimal churn in step-detail-panel. */
export const F = StepPanelField;

type StepPanelInputProps = Omit<ComponentProps<typeof Input>, 'onChange'> & {
  onValueCommit: (value: string) => void;
  commitDelayMs?: number;
};

/** Text input with local draft — keystrokes do not re-render the parent step panel. */
export function StepPanelInput({
  value,
  onValueCommit,
  commitDelayMs = 250,
  onBlur,
  ...props
}: StepPanelInputProps) {
  const [draft, setDraft] = useState(String(value ?? ''));
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const committedValueRef = useRef(String(value ?? ''));

  const debouncedCommit = useDebouncedCallback(onValueCommit, commitDelayMs);

  useEffect(() => {
    const next = String(value ?? '');
    committedValueRef.current = next;
    setDraft(next);
  }, [value]);

  useEffect(
    () => () => {
      const pending = draftRef.current;
      if (pending === committedValueRef.current) return;
      onValueCommit(pending);
      committedValueRef.current = pending;
    },
    [onValueCommit]
  );

  return (
    <Input
      {...props}
      value={draft}
      onChange={(e) => {
        const next = e.target.value;
        setDraft(next);
        debouncedCommit(next);
      }}
      onBlur={(e) => {
        const pending = draftRef.current;
        onValueCommit(pending);
        committedValueRef.current = pending;
        onBlur?.(e);
      }}
    />
  );
}

type StepPanelTextareaProps = Omit<
  ComponentProps<'textarea'>,
  'onChange' | 'value'
> & {
  value: string;
  onValueCommit: (value: string) => void;
  commitDelayMs?: number;
};

export function StepPanelTextarea({
  value,
  onValueCommit,
  commitDelayMs = 250,
  className,
  onBlur,
  ...props
}: StepPanelTextareaProps) {
  const [draft, setDraft] = useState(value ?? '');
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const committedValueRef = useRef(value ?? '');

  const debouncedCommit = useDebouncedCallback(onValueCommit, commitDelayMs);

  useEffect(() => {
    const next = value ?? '';
    committedValueRef.current = next;
    setDraft(next);
  }, [value]);

  useEffect(
    () => () => {
      const pending = draftRef.current;
      if (pending === committedValueRef.current) return;
      onValueCommit(pending);
      committedValueRef.current = pending;
    },
    [onValueCommit]
  );

  return (
    <textarea
      {...props}
      className={className}
      value={draft}
      onChange={(e) => {
        const next = e.target.value;
        setDraft(next);
        debouncedCommit(next);
      }}
      onBlur={(e) => {
        const pending = draftRef.current;
        onValueCommit(pending);
        committedValueRef.current = pending;
        onBlur?.(e);
      }}
    />
  );
}

export function StepPanelSection({
  title,
  badge,
  children,
  className
}: {
  title?: string;
  badge?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        'space-y-3 rounded-lg border border-border/60 bg-muted/15 p-3',
        className
      )}
    >
      {title ? (
        <div className='flex items-center justify-between gap-2'>
          <h4 className='text-xs font-semibold text-foreground'>{title}</h4>
          {badge}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function StepPanelHint({ children }: { children: ReactNode }) {
  return (
    <p className='rounded-md bg-muted/40 px-2.5 py-2 text-[11px] leading-relaxed text-muted-foreground'>
      {children}
    </p>
  );
}

export function StepPanelToggle({
  label,
  description,
  checked,
  onCheckedChange,
  className
}: {
  label: ReactNode;
  description?: ReactNode;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  className?: string;
}) {
  return (
    <label
      className={cn(
        'flex cursor-pointer items-start gap-3 rounded-lg border border-border/60 bg-background/90 px-3 py-2.5 transition-colors',
        checked && 'border-primary/25 bg-primary/[0.04]',
        className
      )}
    >
      <Switch
        checked={checked}
        onCheckedChange={onCheckedChange}
        className='mt-0.5 shrink-0'
      />
      <div className='min-w-0 flex-1 space-y-0.5'>
        <div className='text-xs font-medium leading-snug text-foreground'>
          {label}
        </div>
        {description ? (
          <div className='text-[11px] leading-relaxed text-muted-foreground'>
            {description}
          </div>
        ) : null}
      </div>
    </label>
  );
}

export function StepPanelHeader({ step }: { step: FlowStep }) {
  const { getStepTypeName } = useCampaignFlowI18n();
  const typeName = formatStepLabelForCard(getStepTypeName(step.type));
  const userTitle = String((step as { title?: string }).title ?? '').trim();
  const summary = getStepSummary(step).trim();

  const subtitle = userTitle
    ? summary
      ? `${userTitle} · ${summary}`
      : userTitle
    : summary || undefined;

  return (
    <div className='flex items-start gap-3 border-b border-border/60 bg-muted/20 px-3 py-3 sm:px-4'>
      <span className='flex size-10 shrink-0 items-center justify-center rounded-lg bg-background ring-1 ring-border/60'>
        <StepIcon type={step.type} size={18} />
      </span>
      <div className='min-w-0 flex-1 pt-0.5'>
        <h3 className='text-sm font-semibold leading-tight text-foreground'>
          {typeName}
        </h3>
        {subtitle ? (
          <p className='mt-0.5 line-clamp-2 text-[11px] leading-snug text-muted-foreground'>
            {subtitle}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export function StepPanelMetaFields({
  step,
  commitStep,
  t
}: {
  step: FlowStep;
  commitStep: (next: FlowStep) => void;
  t: ReturnType<typeof useTranslations<'campaignsFeature.stepEditor'>>;
}) {
  const tSec = useTranslations('campaignsFeature.stepEditor.sections');

  return (
    <StepPanelSection title={tSec('general')}>
      <StepPanelField label={t('common.titleOptional')}>
        <StepPanelInput
          className='h-9 text-sm'
          placeholder={t('common.titlePlaceholder')}
          value={(step as { title?: string }).title ?? ''}
          onValueCommit={(title) =>
            commitStep({ ...step, title: title || undefined } as FlowStep)
          }
        />
      </StepPanelField>
      <StepPanelField label={t('common.descriptionOptional')}>
        <StepPanelInput
          className='h-9 text-sm'
          placeholder={t('common.descriptionPlaceholder')}
          value={(step as { description?: string }).description ?? ''}
          onValueCommit={(description) =>
            commitStep({
              ...step,
              description: description || undefined
            } as FlowStep)
          }
        />
      </StepPanelField>
    </StepPanelSection>
  );
}

type ErrorPolicyValue = '' | 'continue' | 'stop' | 'pause';

function resolveErrorPolicyValue(step: FlowStep): ErrorPolicyValue {
  const p = step.on_error ?? '';
  if (p === 'continue' || p === 'stop' || p === 'pause') return p;
  return '';
}

export function StepErrorPolicySection({
  step,
  update
}: {
  step: FlowStep;
  update: (patch: Partial<FlowStep>) => void;
}) {
  const t = useTranslations('campaignsFeature.stepEditor.errorPolicy');
  const policy = resolveErrorPolicyValue(step);

  const effective = useMemo(() => {
    if (policy === 'continue') return t('effectiveContinue');
    if (policy === 'stop') return t('effectiveStop');
    if (policy === 'pause') return t('effectivePause');
    if (step.ignore_error === true) return t('effectiveIgnoreFlag');
    return t('effectiveScenarioDefault');
  }, [policy, step.ignore_error, t]);

  return (
    <StepPanelSection
      title={t('title')}
      badge={
        <Badge variant='outline' className='text-[10px] font-normal'>
          {t('optionalBadge')}
        </Badge>
      }
      className='bg-muted/10'
    >
      <p className='text-[11px] leading-relaxed text-muted-foreground'>
        {t('intro')}
      </p>

      <StepPanelToggle
        label={t('ignoreLabel')}
        description={t('ignoreDescription')}
        checked={step.ignore_error === true}
        onCheckedChange={(checked) =>
          update({ ignore_error: checked || undefined })
        }
      />

      <StepPanelField label={t('policyLabel')}>
        <RadioGroup
          value={policy}
          onValueChange={(v) =>
            update({ on_error: (v as ErrorPolicyValue) || undefined })
          }
          className='gap-2'
        >
          {(
            [
              { value: '', label: t('policyInherit') },
              { value: 'continue', label: t('policyContinue') },
              { value: 'stop', label: t('policyStop') },
              { value: 'pause', label: t('policyPause') }
            ] as const
          ).map((opt) => (
            <label
              key={opt.value || 'inherit'}
              className='flex cursor-pointer items-start gap-2.5 rounded-md border border-transparent px-1 py-1 hover:bg-muted/40 has-[[data-state=checked]]:border-border/60 has-[[data-state=checked]]:bg-background/80'
            >
              <RadioGroupItem
                value={opt.value}
                id={`err-policy-${opt.value || 'inherit'}`}
                className='mt-0.5'
              />
              <span className='text-[11px] leading-snug text-foreground'>
                {opt.label}
              </span>
            </label>
          ))}
        </RadioGroup>
      </StepPanelField>

      <div className='rounded-md border border-border/50 bg-background/80 px-2.5 py-2 text-[11px] leading-relaxed text-muted-foreground'>
        {t('effectivePrefix')}{' '}
        <span className='font-medium text-foreground'>{effective}</span>
      </div>
    </StepPanelSection>
  );
}

export function StepRetryPolicySection({
  step,
  update
}: {
  step: FlowStep;
  update: (patch: Partial<FlowStep>) => void;
}) {
  const t = useTranslations('campaignsFeature.stepEditor.retryPolicy');
  const suppressRetryPatchRef = useRef(false);
  const suppressRetryPatchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  );
  const enabled = !!(
    step.retry &&
    typeof step.retry === 'object' &&
    Object.keys(step.retry).length > 0
  );
  const policy = coerceStepRetryPolicy(step.retry);

  useEffect(
    () => () => {
      if (suppressRetryPatchTimerRef.current) {
        clearTimeout(suppressRetryPatchTimerRef.current);
      }
    },
    []
  );

  const updateRetry = useCallback(
    (retry: unknown) => {
      if (suppressRetryPatchRef.current) return;
      update({ retry: coerceStepRetryPolicy(retry) });
    },
    [update]
  );

  const setRetryEnabled = useCallback(
    (checked: boolean) => {
      if (!checked) {
        suppressRetryPatchRef.current = true;
        if (suppressRetryPatchTimerRef.current) {
          clearTimeout(suppressRetryPatchTimerRef.current);
        }
        update(retryPatchForEnabledState(step, false));
        suppressRetryPatchTimerRef.current = setTimeout(() => {
          suppressRetryPatchRef.current = false;
          suppressRetryPatchTimerRef.current = null;
        }, 300);
        return;
      }
      update(retryPatchForEnabledState(step, true));
    },
    [step, update]
  );

  const setCap = (raw: string) => {
    const next = coerceStepRetryPolicy(step.retry);
    if (!raw.trim()) {
      delete next.backoff_cap_ms;
    } else {
      next.backoff_cap_ms = Number(raw);
    }
    updateRetry(next);
  };

  return (
    <StepPanelSection
      title={t('title')}
      badge={
        <Badge variant='outline' className='text-[10px] font-normal'>
          {t('optionalBadge')}
        </Badge>
      }
      className='bg-muted/10'
    >
      <StepPanelToggle
        label={t('enableLabel')}
        description={t('enableDescription')}
        checked={enabled}
        onCheckedChange={setRetryEnabled}
      />

      {enabled ? (
        <div className='space-y-3'>
          <div className='grid grid-cols-2 gap-3'>
            <StepPanelField label={t('attemptsLabel')}>
              <Input
                type='number'
                min={2}
                max={10}
                className='h-8 text-xs'
                value={policy.max_attempts}
                onChange={(e) =>
                  updateRetry(
                    withRetryField(
                      step.retry,
                      'max_attempts',
                      Number(e.target.value)
                    )
                  )
                }
              />
            </StepPanelField>

            <StepPanelField label={t('backoffMsLabel')}>
              <Input
                type='number'
                min={0}
                max={60000}
                step={100}
                className='h-8 text-xs'
                value={policy.backoff_ms}
                onChange={(e) =>
                  updateRetry(
                    withRetryField(
                      step.retry,
                      'backoff_ms',
                      Number(e.target.value)
                    )
                  )
                }
              />
            </StepPanelField>

            <StepPanelField label={t('jitterLabel')}>
              <Input
                type='number'
                min={0}
                max={1}
                step={0.05}
                className='h-8 text-xs'
                value={policy.jitter}
                onChange={(e) =>
                  updateRetry(
                    withRetryField(step.retry, 'jitter', Number(e.target.value))
                  )
                }
              />
            </StepPanelField>

            <StepPanelField label={t('capMsLabel')}>
              <Input
                type='number'
                min={0}
                max={60000}
                step={1000}
                className='h-8 text-xs'
                value={policy.backoff_cap_ms ?? ''}
                placeholder='60000'
                onChange={(e) => setCap(e.target.value)}
              />
            </StepPanelField>
          </div>

          <StepPanelField label={t('strategyLabel')}>
            <RadioGroup
              value={policy.backoff_strategy}
              onValueChange={(value) =>
                updateRetry(
                  withRetryField(
                    step.retry,
                    'backoff_strategy',
                    value as RetryBackoffStrategy
                  )
                )
              }
              className='grid grid-cols-2 gap-2'
            >
              {(
                [
                  { value: 'exponential', label: t('strategyExponential') },
                  { value: 'fixed', label: t('strategyFixed') }
                ] as const
              ).map((opt) => (
                <label
                  key={opt.value}
                  className='flex cursor-pointer items-center gap-2 rounded-md border border-border/60 bg-background/80 px-2.5 py-2 text-[11px] hover:bg-muted/40 has-[[data-state=checked]]:border-primary/30 has-[[data-state=checked]]:bg-primary/[0.04]'
                >
                  <RadioGroupItem value={opt.value} />
                  <span>{opt.label}</span>
                </label>
              ))}
            </RadioGroup>
          </StepPanelField>

          <StepPanelField label={t('reasonsLabel')}>
            <StepPanelTextarea
              className='min-h-16 w-full resize-y rounded-md border border-input bg-background px-3 py-2 font-mono text-xs ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2'
              value={formatRetryReasons(step.retry)}
              placeholder={t('reasonsPlaceholder')}
              onValueCommit={(raw) =>
                updateRetry(
                  withRetryField(
                    step.retry,
                    'retryable_reasons',
                    parseRetryReasons(raw)
                  )
                )
              }
            />
            <p className='text-[11px] leading-relaxed text-muted-foreground'>
              {t('reasonsHint')}
            </p>
          </StepPanelField>
        </div>
      ) : null}
    </StepPanelSection>
  );
}

export function AppLifecycleStepFields({
  step,
  update,
  tApp
}: {
  step: FlowStep;
  update: (fields: Partial<FlowStep>) => void;
  tApp: ReturnType<
    typeof useTranslations<'campaignsFeature.stepEditor.appLifecycle'>
  >;
}) {
  const tSec = useTranslations('campaignsFeature.stepEditor.sections');

  if (step.type === 'stop_app') {
    return (
      <StepPanelSection title={tSec('appTarget')}>
        <StepPanelField label={tApp('packageLabel')}>
          <Input
            className='h-9 font-mono text-sm'
            value={step.package ?? ''}
            onChange={(e) => update({ package: e.target.value })}
            placeholder={tApp('placeholderPackage')}
          />
        </StepPanelField>
      </StepPanelSection>
    );
  }

  if (step.type === 'clear_app') {
    return (
      <StepPanelSection title={tSec('appTarget')}>
        <StepPanelField label={tApp('packageLabel')}>
          <Input
            className='h-9 font-mono text-sm'
            value={step.package ?? ''}
            onChange={(e) => update({ package: e.target.value })}
            placeholder={tApp('placeholderPackage')}
          />
        </StepPanelField>
        <StepPanelHint>
          <span className='text-amber-700 dark:text-amber-300'>
            {tApp('clearWarning')}
          </span>
        </StepPanelHint>
      </StepPanelSection>
    );
  }

  if (step.type === 'wait_app') {
    return (
      <>
        <StepPanelSection title={tSec('appTarget')}>
          <StepPanelField label={tApp('packageLabel')}>
            <Input
              className='h-9 font-mono text-sm'
              value={step.package ?? ''}
              onChange={(e) => update({ package: e.target.value })}
              placeholder={tApp('placeholderPackage')}
            />
          </StepPanelField>
        </StepPanelSection>
        <StepPanelSection title={tSec('timing')}>
          <StepPanelField label={tApp('timeoutSeconds')}>
            <Input
              type='number'
              min={0.5}
              step={0.5}
              className='h-9 w-32 text-sm'
              value={step.timeout ?? 20}
              onChange={(e) =>
                update({ timeout: Number(e.target.value) || 20 })
              }
            />
          </StepPanelField>
          <StepPanelToggle
            label={tApp('waitForeground')}
            checked={step.front !== false}
            onCheckedChange={(checked) => update({ front: checked })}
          />
        </StepPanelSection>
      </>
    );
  }

  if (step.type === 'launch_app') {
    return (
      <>
        <StepPanelSection title={tSec('appTarget')}>
          <StepPanelField label={tApp('packageLabel')}>
            <Input
              className='h-9 font-mono text-sm'
              value={step.package ?? ''}
              onChange={(e) => update({ package: e.target.value })}
              placeholder={tApp('placeholderChrome')}
            />
          </StepPanelField>
          <StepPanelField label={tApp('activityLabel')}>
            <Input
              className='h-9 font-mono text-sm'
              value={step.activity ?? step.component ?? ''}
              onChange={(e) =>
                update({
                  activity: e.target.value || undefined,
                  component: e.target.value || undefined
                })
              }
              placeholder={tApp('activityPlaceholder')}
            />
          </StepPanelField>
        </StepPanelSection>
        <StepPanelSection title={tSec('appOptions')}>
          <StepPanelToggle
            label={tApp('stopBefore')}
            description={tApp('stopBeforeHint')}
            checked={!!step.stop_before}
            onCheckedChange={(checked) => update({ stop_before: checked })}
          />
          <StepPanelToggle
            label={tApp('useMonkey')}
            description={tApp('useMonkeyHint')}
            checked={!!step.use_monkey}
            onCheckedChange={(checked) => update({ use_monkey: checked })}
          />
        </StepPanelSection>
        <StepPanelSection title={tSec('timing')}>
          <StepPanelField label={tApp('waitAfterLaunch')}>
            <Input
              type='number'
              min={0}
              step={0.1}
              className='h-9 w-32 text-sm'
              value={step.wait_after ?? 2}
              onChange={(e) =>
                update({ wait_after: Number(e.target.value) || 0 })
              }
            />
          </StepPanelField>
        </StepPanelSection>
      </>
    );
  }

  return null;
}
