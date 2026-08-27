'use client';

import type { ReactNode } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Database,
  ListChecks,
  Route,
  Target
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { ControlRecordPageSummary } from '@/features/devices/lib/control-record-page-summary';

export type TargetBindingOverviewLabels = {
  title: string;
  source: string;
  targets: string;
  flow: string;
  flowUsesTarget: string;
  flowDoesNotUseTarget: string;
  bindingVariables: string;
  unusedVariables: string;
  targetValuePreview: string;
  catalogTargetSource: string;
  manualTargetSource: string;
  catalogTargetHint: string;
  manualTargetHint: string;
  pageTarget: string;
  groupTarget: string;
};

export function TargetBindingOverview({
  summary,
  labels,
  action,
  sourceDescription,
  compact = false
}: {
  summary: ControlRecordPageSummary;
  labels: TargetBindingOverviewLabels;
  action?: ReactNode;
  sourceDescription?: string;
  compact?: boolean;
}) {
  const hasUsageSignal =
    summary.usedBindingKeys.length > 0 || summary.unusedBindingKeys.length > 0;
  const flowUsesTarget =
    summary.usedBindingKeys.length > 0 && summary.usageWarning == null;
  const statusText = flowUsesTarget
    ? labels.flowUsesTarget
    : labels.flowDoesNotUseTarget;
  const targetNoun =
    summary.targetType === 'group' ? labels.groupTarget : labels.pageTarget;
  const targetSourceLabel =
    summary.targetInputKind === 'catalog'
      ? labels.catalogTargetSource
      : labels.manualTargetSource;
  const targetHint =
    summary.targetInputKind === 'catalog'
      ? labels.catalogTargetHint
      : labels.manualTargetHint;

  return (
    <section
      className={cn(
        'rounded-lg border bg-background text-xs',
        summary.usageWarning ? 'border-amber-500/35' : 'border-border/80',
        compact ? 'p-3' : 'p-3.5'
      )}
    >
      <div className='flex flex-wrap items-start justify-between gap-2'>
        <div className='flex min-w-0 items-start gap-2'>
          <ListChecks className='mt-0.5 size-4 shrink-0 text-muted-foreground' />
          <div className='min-w-0'>
            <h3 className='text-sm font-medium leading-5 text-foreground'>
              {labels.title}
            </h3>
            <p className='truncate text-muted-foreground'>
              {summary.sourceLabel}
            </p>
          </div>
        </div>
        <div className='flex shrink-0 items-center gap-1.5'>
          {hasUsageSignal ? (
            <Badge
              variant='outline'
              className={cn(
                'gap-1.5 rounded font-normal',
                flowUsesTarget
                  ? 'border-emerald-500/35 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                  : 'border-amber-500/35 bg-amber-500/10 text-amber-800 dark:text-amber-200'
              )}
            >
              {flowUsesTarget ? (
                <CheckCircle2 className='size-3' />
              ) : (
                <AlertTriangle className='size-3' />
              )}
              {statusText}
            </Badge>
          ) : null}
          {action}
        </div>
      </div>

      <div
        className={cn(
          'mt-3 grid min-w-0 gap-2',
          compact
            ? 'grid-cols-1'
            : 'lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1.2fr)_auto_minmax(0,1fr)]'
        )}
      >
        <BindingColumn
          icon={<Database className='size-3.5' />}
          title={labels.source}
        >
          <p className='font-medium text-foreground'>{summary.sourceLabel}</p>
          <p className='mt-1 leading-relaxed text-muted-foreground'>
            {sourceDescription ?? summary.sourceDescription}
          </p>
        </BindingColumn>

        <FlowArrow compact={compact} />

        <BindingColumn
          icon={<Target className='size-3.5' />}
          title={labels.targets}
        >
          <div className='mb-2 flex min-w-0 flex-wrap items-center gap-1.5'>
            <span className='text-sm font-medium text-foreground'>
              {summary.count} {targetNoun}
            </span>
            <Badge
              variant='outline'
              className='rounded font-normal text-muted-foreground'
            >
              {targetSourceLabel}
            </Badge>
          </div>
          <p className='mb-2 text-[11px] leading-relaxed text-muted-foreground'>
            {targetHint || labels.targetValuePreview}
          </p>
          <div className='grid gap-1.5'>
            {summary.labels.map((target, index) => (
              <div
                key={`${summary.targetType}-${target}-${index}`}
                className='flex min-w-0 items-center gap-2 rounded-md border bg-background px-2 py-1.5'
              >
                <span className='flex h-5 min-w-5 shrink-0 items-center justify-center rounded border bg-muted/60 text-[10px] text-muted-foreground'>
                  {index + 1}
                </span>
                <span className='min-w-0 flex-1 truncate text-foreground'>
                  {target}
                </span>
              </div>
            ))}
          </div>
        </BindingColumn>

        <FlowArrow compact={compact} />

        <BindingColumn
          icon={<Route className='size-3.5' />}
          title={labels.flow}
        >
          {summary.usedBindingKeys.length > 0 ? (
            <VariableKeyList
              label={labels.bindingVariables}
              keys={summary.usedBindingKeys}
            />
          ) : null}
          {summary.unusedBindingKeys.length > 0 ? (
            <VariableKeyList
              label={labels.unusedVariables}
              keys={summary.unusedBindingKeys}
              muted
            />
          ) : null}
          {summary.bindingKeys.length > 0 &&
          summary.usedBindingKeys.length === 0 &&
          summary.unusedBindingKeys.length === 0 ? (
            <VariableKeyList
              label={labels.bindingVariables}
              keys={summary.bindingKeys}
            />
          ) : null}
        </BindingColumn>
      </div>

      {summary.warning || summary.usageWarning ? (
        <div className='mt-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-2.5 py-2 text-amber-800 dark:text-amber-200'>
          {summary.warning ?? summary.usageWarning}
        </div>
      ) : null}
    </section>
  );
}

function BindingColumn({
  icon,
  title,
  children
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className='min-w-0 rounded-md border bg-muted/20 p-2.5'>
      <div className='mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase text-muted-foreground'>
        {icon}
        {title}
      </div>
      {children}
    </div>
  );
}

function FlowArrow({ compact }: { compact: boolean }) {
  return (
    <div
      className={cn(
        'items-center justify-center text-muted-foreground/70',
        compact ? 'hidden' : 'hidden lg:flex'
      )}
    >
      <ArrowRight className='size-4' />
    </div>
  );
}

function VariableKeyList({
  label,
  keys,
  muted = false
}: {
  label: string;
  keys: string[];
  muted?: boolean;
}) {
  return (
    <div className='space-y-1.5'>
      <p className={muted ? 'text-muted-foreground' : 'text-foreground'}>
        {label}
      </p>
      <div className='flex flex-wrap gap-1'>
        {keys.map((key) => (
          <code
            key={key}
            className={cn(
              'max-w-full truncate rounded border bg-background px-1.5 py-0.5 font-mono text-[11px]',
              muted ? 'text-muted-foreground' : 'text-foreground'
            )}
            title={key}
          >
            {key}
          </code>
        ))}
      </div>
    </div>
  );
}
