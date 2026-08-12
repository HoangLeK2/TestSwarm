'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Database,
  CircleAlert,
  Loader2,
  Play,
  Settings2,
  Sparkles,
  Smartphone
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { cn } from '@/lib/utils';
import { continuousCrawlApi } from '../services/api';
import type { CampaignDeviceOut } from '../types';
import type { DispatchScenarioItem } from './dispatch-campaign-dialog';
import type { ContinuousCrawlPreflight } from '../lib/continuous-crawl-monitor';
import {
  isAlreadyActiveError,
  readinessProblemFromError,
  type ReadinessProblem
} from '../lib/automation-start';

export type AutomationStartStep = 'goal' | 'source' | 'operation' | 'review';
type Step = AutomationStartStep;
const steps: Step[] = ['goal', 'source', 'operation', 'review'];

function findSource(
  steps: unknown
): { platform: string; entityType: string } | null {
  if (!Array.isArray(steps)) return null;
  for (const step of steps) {
    if (!step || typeof step !== 'object') continue;
    const row = step as Record<string, unknown>;
    if (row.type === 'use_source_pool') {
      return {
        platform: String(row.platform || 'facebook'),
        entityType: String(row.entity_type || 'group')
      };
    }
    for (const key of ['steps', 'then', 'else']) {
      const nested = findSource(row[key]);
      if (nested) return nested;
    }
  }
  return null;
}

export function ContinuousCrawlStartDialog({
  open,
  campaignName,
  campaignId,
  devices,
  scenarios,
  initialStep = 'goal',
  onClose,
  onStarted,
  onManageDevices,
  onManageTargets,
  onEditConfiguration
}: {
  open: boolean;
  campaignName: string;
  campaignId: string;
  devices: CampaignDeviceOut[];
  scenarios: DispatchScenarioItem[];
  initialStep?: AutomationStartStep;
  onClose: () => void;
  onStarted: () => void;
  onManageDevices: () => void;
  onManageTargets: () => void;
  onEditConfiguration: () => void;
}) {
  const t = useTranslations('campaignsFeature.automationStart');
  const [step, setStep] = useState<Step>('goal');
  const [preflight, setPreflight] = useState<ContinuousCrawlPreflight | null>(
    null
  );
  const [checking, setChecking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [readinessError, setReadinessError] = useState<{
    message: string;
    problem: ReadinessProblem;
  } | null>(null);
  const stepIndex = steps.indexOf(step);
  const source = scenarios
    .map((scenario) => findSource(scenario.steps))
    .find(Boolean);

  const checkReadiness = useCallback(async () => {
    setChecking(true);
    setReadinessError(null);
    try {
      setPreflight(await continuousCrawlApi.preflight(campaignId));
    } catch (error) {
      setPreflight(null);
      setReadinessError({
        message: formatFarmApiError(error, t('checkFailed')),
        problem: readinessProblemFromError(error)
      });
    } finally {
      setChecking(false);
    }
  }, [campaignId, t]);

  useEffect(() => {
    if (!open) return;
    setStep(initialStep);
    setPreflight(null);
    setChecking(false);
    setStarting(false);
    setReadinessError(null);
    if (initialStep === 'review') void checkReadiness();
  }, [checkReadiness, initialStep, open]);

  const next = () => {
    const nextStep = steps[Math.min(steps.length - 1, stepIndex + 1)];
    setStep(nextStep);
    if (nextStep === 'review' && !preflight) void checkReadiness();
  };

  const start = async () => {
    setStarting(true);
    try {
      await continuousCrawlApi.start(campaignId);
      toast.success(t('started'));
      onStarted();
    } catch (error) {
      if (isAlreadyActiveError(error)) {
        toast.info(t('alreadyActive'));
        onStarted();
        return;
      }
      toast.error(formatFarmApiError(error, t('startFailed')));
    } finally {
      setStarting(false);
    }
  };

  const labels: Record<Step, string> = {
    goal: t('steps.goal'),
    source: t('steps.source'),
    operation: t('steps.operation'),
    review: t('steps.review')
  };

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
      <DialogContent className='flex max-h-[92vh] max-w-3xl flex-col gap-0 overflow-hidden p-0'>
        <DialogHeader className='border-b px-5 py-4 text-left'>
          <DialogTitle>{t('title')}</DialogTitle>
          <DialogDescription>{campaignName}</DialogDescription>
        </DialogHeader>

        <div className='grid grid-cols-4 border-b bg-muted/30 px-3 py-3 sm:px-5'>
          {steps.map((item, index) => (
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
                {labels[item]}
              </span>
            </div>
          ))}
        </div>

        <div className='min-h-[340px] overflow-y-auto px-5 py-6'>
          {step === 'goal' ? (
            <div className='mx-auto max-w-xl space-y-5'>
              <div>
                <p className='text-xs font-medium text-primary'>
                  {t('goal.eyebrow')}
                </p>
                <h3 className='mt-1 text-xl font-semibold'>
                  {t('goal.title')}
                </h3>
                <p className='mt-2 text-sm text-muted-foreground'>
                  {t('goal.description')}
                </p>
              </div>
              <div className='rounded-xl border bg-primary/[0.04] p-5'>
                <Sparkles className='mb-3 size-5 text-primary' />
                <p className='font-semibold'>{campaignName}</p>
                <p className='mt-1 text-sm text-muted-foreground'>
                  {t('goal.scenarioCount', { count: scenarios.length })}
                </p>
              </div>
            </div>
          ) : null}

          {step === 'source' ? (
            <div className='mx-auto max-w-xl space-y-5'>
              <div>
                <p className='text-xs font-medium text-primary'>
                  {t('source.eyebrow')}
                </p>
                <h3 className='mt-1 text-xl font-semibold'>
                  {t('source.title')}
                </h3>
                <p className='mt-2 text-sm text-muted-foreground'>
                  {t('source.description')}
                </p>
              </div>
              <div className='flex items-start gap-4 rounded-xl border p-5'>
                <div className='rounded-full bg-primary/10 p-2.5 text-primary'>
                  <Database className='size-5' />
                </div>
                <div>
                  <p className='font-semibold capitalize'>
                    {source
                      ? `${source.platform} · ${source.entityType}`
                      : t('source.configured')}
                  </p>
                  <p className='mt-1 text-sm text-muted-foreground'>
                    {t('source.deduplication')}
                  </p>
                </div>
              </div>
              <p className='rounded-lg bg-muted/60 px-4 py-3 text-xs text-muted-foreground'>
                {t('source.snapshot')}
              </p>
            </div>
          ) : null}

          {step === 'operation' ? (
            <div className='mx-auto max-w-xl space-y-5'>
              <div>
                <p className='text-xs font-medium text-primary'>
                  {t('operation.eyebrow')}
                </p>
                <h3 className='mt-1 text-xl font-semibold'>
                  {t('operation.title')}
                </h3>
                <p className='mt-2 text-sm text-muted-foreground'>
                  {t('operation.description')}
                </p>
              </div>
              <div className='grid gap-3 sm:grid-cols-2'>
                <div className='rounded-xl border p-4'>
                  <Smartphone className='mb-3 size-5 text-primary' />
                  <p className='font-semibold'>
                    {t('operation.devices', { count: devices.length })}
                  </p>
                  <p className='mt-1 text-xs text-muted-foreground'>
                    {t('operation.devicesHelp')}
                  </p>
                </div>
                <div className='rounded-xl border p-4'>
                  <Settings2 className='mb-3 size-5 text-primary' />
                  <p className='font-semibold'>{t('operation.automatic')}</p>
                  <p className='mt-1 text-xs text-muted-foreground'>
                    {t('operation.automaticHelp')}
                  </p>
                </div>
              </div>
            </div>
          ) : null}

          {step === 'review' ? (
            <div className='mx-auto max-w-xl space-y-5'>
              <div>
                <p className='text-xs font-medium text-primary'>
                  {t('review.eyebrow')}
                </p>
                <h3 className='mt-1 text-xl font-semibold'>
                  {t('review.title')}
                </h3>
                <p className='mt-2 text-sm text-muted-foreground'>
                  {t('review.description')}
                </p>
              </div>
              {checking ? (
                <div className='flex items-center gap-3 rounded-xl border p-5 text-sm text-muted-foreground'>
                  <Loader2 className='size-4 animate-spin' />
                  {t('review.checking')}
                </div>
              ) : preflight ? (
                <div className='space-y-2 rounded-xl border p-5'>
                  <ReadyRow
                    label={t('review.sources', {
                      count: preflight.target_count ?? 0
                    })}
                  />
                  <ReadyRow
                    label={t('review.devices', {
                      count: preflight.device_count
                    })}
                  />
                  <ReadyRow label={t('review.scenario')} />
                  <div className='mt-3 divide-y border-t pt-2'>
                    {(preflight.device_targets ?? []).map((device) => (
                      <div
                        key={device.device_id}
                        className='flex items-center justify-between gap-4 py-2 text-xs'
                      >
                        <span className='min-w-0 truncate'>
                          {device.device_name || device.device_serial}
                        </span>
                        <span className='shrink-0 tabular-nums text-muted-foreground'>
                          {t('review.targetsForDevice', {
                            count: device.target_count
                          })}
                        </span>
                      </div>
                    ))}
                  </div>
                  {preflight.warnings.map((warning) => (
                    <p key={warning} className='text-xs text-amber-700'>
                      {warning}
                    </p>
                  ))}
                </div>
              ) : readinessError ? (
                <div className='space-y-4 rounded-xl border border-destructive/30 bg-destructive/[0.04] p-5'>
                  <div className='flex items-start gap-3'>
                    <CircleAlert className='mt-0.5 size-5 shrink-0 text-destructive' />
                    <div>
                      <p className='font-semibold'>
                        {t(`problems.${readinessError.problem.action}.title`)}
                      </p>
                      <p className='mt-1 text-sm text-muted-foreground'>
                        {readinessError.message}
                      </p>
                      <p className='mt-2 text-xs text-muted-foreground'>
                        {t(`problems.${readinessError.problem.action}.help`)}
                      </p>
                    </div>
                  </div>
                  <div className='flex flex-wrap gap-2'>
                    {readinessError.problem.action === 'devices' ? (
                      <Button size='sm' onClick={onManageDevices}>
                        {t('problems.devices.action')}
                      </Button>
                    ) : readinessError.problem.action === 'targets' ? (
                      <Button size='sm' onClick={onManageTargets}>
                        {t('problems.targets.action')}
                      </Button>
                    ) : readinessError.problem.action === 'source' ||
                      readinessError.problem.action === 'account' ? (
                      <Button size='sm' onClick={onEditConfiguration}>
                        {t(`problems.${readinessError.problem.action}.action`)}
                      </Button>
                    ) : null}
                    <Button
                      size='sm'
                      variant='outline'
                      onClick={() => void checkReadiness()}
                    >
                      {t('review.retry')}
                    </Button>
                  </div>
                </div>
              ) : (
                <Button variant='outline' onClick={() => void checkReadiness()}>
                  {t('review.retry')}
                </Button>
              )}
              <p className='text-sm text-muted-foreground'>
                {t('review.summary', {
                  devices: preflight?.device_count ?? devices.length,
                  targets: preflight?.target_count ?? 0
                })}
              </p>
            </div>
          ) : null}
        </div>

        <DialogFooter className='flex-row items-center justify-between border-t bg-muted/20 px-5 py-4 sm:justify-between'>
          <Button
            variant='ghost'
            onClick={
              stepIndex === 0 ? onClose : () => setStep(steps[stepIndex - 1])
            }
            disabled={starting}
          >
            {stepIndex > 0 ? <ArrowLeft className='mr-1.5 size-4' /> : null}
            {stepIndex === 0 ? t('cancel') : t('back')}
          </Button>
          {step !== 'review' ? (
            <Button onClick={next}>
              {t('next')}
              <ArrowRight className='ml-1.5 size-4' />
            </Button>
          ) : (
            <Button
              onClick={() => void start()}
              disabled={starting || checking || !preflight?.ready}
            >
              {starting ? (
                <Loader2 className='mr-1.5 size-4 animate-spin' />
              ) : (
                <Play className='mr-1.5 size-4' />
              )}
              {starting ? t('starting') : t('start')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReadyRow({ label }: { label: string }) {
  return (
    <div className='flex items-center gap-2 text-sm'>
      <span className='flex size-5 items-center justify-center rounded-full bg-emerald-100 text-emerald-700'>
        <Check className='size-3' />
      </span>
      {label}
    </div>
  );
}
