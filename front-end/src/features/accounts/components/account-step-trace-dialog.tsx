'use client';

import { useMemo, useState, type ReactNode } from 'react';
import { AlertCircle, Footprints } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { ArtifactMonitorTile } from '@/features/campaigns/components/campaign-monitor/artifact-tile';
import { StepRow } from '@/features/campaigns/components/workflow-step-list';
import { useExecutionArtifacts } from '@/features/campaigns/hooks/use-campaigns';
import {
  artifactIsImage,
  resolvedArtifactHref
} from '@/features/campaigns/lib/artifact-monitor-utils';
import { emptyExecutionTrace } from '@/features/campaigns/lib/execution-trace';
import type { ExecutionArtifact } from '@/features/campaigns/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import { Z_CAMPAIGN_MONITOR } from '@/lib/z-index';

import { useAccountRunTaskLog, useAccountRuns } from '../hooks/use-accounts';
import {
  runEventsToLogEntries,
  runStepsToLogEntries
} from '../lib/run-step-log';
import type { AccountOut, AccountRunOut } from '../services/api';

const EMPTY_SCENARIO_NAMES: ReadonlyMap<string, string> = new Map();

function runTimestamp(run: AccountRunOut): string {
  const raw = run.started_at ?? run.created_at;
  if (!raw) return '—';
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString();
}

function runStatusTone(status: string): string {
  if (status === 'failed' || status === 'error') return 'destructive';
  if (status === 'running') return 'default';
  return 'secondary';
}

function RunButton({
  run,
  selected,
  onSelect,
  noCampaignLabel
}: {
  run: AccountRunOut;
  selected: boolean;
  onSelect: () => void;
  noCampaignLabel: string;
}) {
  return (
    <button
      type='button'
      onClick={onSelect}
      aria-current={selected}
      className={cn(
        'w-full rounded-md border px-3 py-2 text-left text-sm transition-colors',
        selected ? 'border-primary bg-accent' : 'hover:bg-accent/50'
      )}
    >
      <div className='flex items-center justify-between gap-2'>
        <span className='font-mono text-xs'>{runTimestamp(run)}</span>
        <Badge
          variant={
            runStatusTone(run.status) as 'default' | 'secondary' | 'destructive'
          }
        >
          {run.status}
        </Badge>
      </div>
      <div className='mt-1 truncate text-xs text-muted-foreground'>
        {run.campaign_id ? run.run_type : noCampaignLabel}
      </div>
    </button>
  );
}

/** Screenshots for one step, if any were captured. */
function StepShots({ artifacts }: { artifacts: readonly ExecutionArtifact[] }) {
  const shots = useMemo(
    () =>
      artifacts.flatMap((artifact) => {
        const href = resolvedArtifactHref(artifact);
        // An artifact whose URL did not resolve has nothing to show, and
        // hierarchy dumps are not images.
        if (!href || !artifactIsImage(artifact, href)) return [];
        return [{ artifact, href }];
      }),
    [artifacts]
  );
  if (shots.length === 0) return null;

  return (
    <div className='mb-3 ml-6 grid gap-2 sm:grid-cols-2'>
      {shots.map(({ artifact, href }, position) => (
        <ArtifactMonitorTile
          key={`${artifact.artifact_type}-${artifact.created_at ?? position}`}
          artifact={artifact}
          href={href}
          label={artifact.artifact_type}
          deviceLabel={artifact.device_serial ?? ''}
          subtitle={artifact.message ?? ''}
          stepNumber={
            artifact.step_index == null ? null : artifact.step_index + 1
          }
          isFail={artifact.ok === false}
          timeLabel={artifact.created_at ?? ''}
          hideDeviceLabel
          compact
        />
      ))}
    </div>
  );
}

function StepTraceBody({ executionId }: { executionId: string | null }) {
  const t = useTranslations('accountsFeature.history.stepTrace');
  const { data, isLoading, isError } = useAccountRunTaskLog(executionId);

  // Events first: they are the only record of steps below depth 0. When a run
  // is older than the event retention window they are gone, and execution_steps
  // — which is never purged — is all that survives. Falling back keeps old runs
  // readable instead of showing an empty panel.
  const { entries, truncated, fromEvents } = useMemo(() => {
    const fromEvents = runEventsToLogEntries(data?.events ?? []);
    if (fromEvents.length > 0) {
      return {
        entries: fromEvents,
        truncated: Boolean(data?.has_more_events),
        fromEvents: true
      };
    }
    return {
      entries: runStepsToLogEntries(data?.steps ?? []),
      truncated: false,
      fromEvents: false
    };
  }, [data]);
  // Screenshots live in their own table, keyed by step_index. Without them the
  // trace can say a step failed but not show what the screen looked like — the
  // one thing a ban investigation actually wants to see. Never polled: these
  // runs are finished.
  const { data: artifacts } = useExecutionArtifacts(
    executionId,
    Boolean(executionId),
    false
  );
  const shotsByStep = useMemo(() => {
    const byStep = new Map<number, ExecutionArtifact[]>();
    for (const artifact of artifacts ?? []) {
      if (artifact.step_index == null) continue;
      const bucket = byStep.get(artifact.step_index);
      if (bucket) bucket.push(artifact);
      else byStep.set(artifact.step_index, [artifact]);
    }
    return byStep;
  }, [artifacts]);

  if (!executionId) {
    return <p className='text-sm text-muted-foreground'>{t('selectRun')}</p>;
  }
  if (isLoading) {
    return <p className='text-sm text-muted-foreground'>{t('loadingSteps')}</p>;
  }
  if (isError) {
    return (
      <p className='flex items-center gap-2 text-sm text-destructive'>
        <AlertCircle className='size-4' />
        {t('stepsError')}
      </p>
    );
  }
  if (entries.length === 0) {
    return <p className='text-sm text-muted-foreground'>{t('emptySteps')}</p>;
  }

  const failedCount = entries.filter((entry) => !entry.ok).length;

  return (
    <div className='space-y-2'>
      <div className='flex flex-wrap gap-3 text-xs text-muted-foreground'>
        <span>{t('stepCount', { count: entries.length })}</span>
        {failedCount > 0 ? (
          <span className='text-destructive'>
            {t('failedCount', { count: failedCount })}
          </span>
        ) : null}
        {!fromEvents ? <span>{t('topLevelOnly')}</span> : null}
        {truncated ? <span>{t('truncated')}</span> : null}
      </div>
      <div>
        {entries.map((entry, position) => (
          // step_path first: a step inside a loop repeats its index and id on
          // every iteration, and only the path carries the iteration number.
          <div
            key={`${entry.step_path ?? entry.step_id ?? entry.index}-${position}`}
          >
            <StepRow
              index={entry.index}
              logEntry={entry}
              // A persisted run is finished by definition: nothing here is
              // live, so the "currently running" inputs StepRow needs are inert.
              isCurrentlyRunning={false}
              currentStepType=''
              currentMessage=''
              currentTrace={emptyExecutionTrace()}
              loopIter={entry.loop_iter ?? null}
              isPending={false}
              status={entry.ok ? 'completed' : 'failed'}
              depth={entry.depth}
              branchLabel={entry.branch ?? undefined}
              isLast={position === entries.length - 1}
              scenarioNamesById={EMPTY_SCENARIO_NAMES}
            />
            <StepShots artifacts={shotsByStep.get(entry.index) ?? []} />
          </div>
        ))}
      </div>
    </div>
  );
}

export function AccountStepTraceDialog({
  account,
  trigger
}: {
  account: AccountOut;
  /** Supplied when hosted in a dropdown, which owns its own item markup. */
  trigger?: ReactNode;
}) {
  const t = useTranslations('accountsFeature.history.stepTrace');
  const [open, setOpen] = useState(false);
  const [executionId, setExecutionId] = useState<string | null>(null);
  // Runs load only once the dialog is opened: this is a forensic view, not
  // something every row in the account table should be fetching.
  const { data, isLoading, isError } = useAccountRuns(account.id, {
    enabled: open
  });
  const runs = data?.items ?? [];

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button variant='ghost' size='sm' className='h-8 gap-1'>
            <Footprints className='size-3.5' />
            {t('trigger')}
          </Button>
        )}
      </DialogTrigger>
      {/* sm:max-w-*, not max-w-*: DialogContent carries sm:max-w-lg, and a
          non-responsive class loses to it at every width that matters. Without
          the prefix the dialog stays 512px and the failure message — the one
          line this view exists to show — is clipped. */}
      <DialogContent className='sm:max-w-5xl' zIndex={Z_CAMPAIGN_MONITOR}>
        <DialogHeader>
          <DialogTitle>
            {t('title', {
              username: account.display_name || account.username || account.id
            })}
          </DialogTitle>
          <DialogDescription>{t('description')}</DialogDescription>
        </DialogHeader>

        <div className='grid gap-4 md:grid-cols-[minmax(0,240px)_minmax(0,1fr)]'>
          <div className='space-y-2'>
            <p className='text-xs font-medium text-muted-foreground'>
              {t('runsHeading')}
            </p>
            {isLoading ? (
              <p className='text-sm text-muted-foreground'>
                {t('loadingRuns')}
              </p>
            ) : isError ? (
              <p className='flex items-center gap-2 text-sm text-destructive'>
                <AlertCircle className='size-4' />
                {t('runsError')}
              </p>
            ) : runs.length === 0 ? (
              <p className='text-sm text-muted-foreground'>{t('emptyRuns')}</p>
            ) : (
              <ScrollArea className='h-[60vh] pr-2'>
                <div className='space-y-1'>
                  {runs.map((run) => (
                    <RunButton
                      key={run.id}
                      run={run}
                      selected={run.id === executionId}
                      onSelect={() => setExecutionId(run.id)}
                      noCampaignLabel={t('noCampaign')}
                    />
                  ))}
                </div>
              </ScrollArea>
            )}
          </div>

          {/* min-w-0: a grid item defaults to min-content width, so a long
              step message would push the column wider than the dialog and get
              clipped instead of wrapping. */}
          <div className='min-w-0 space-y-2'>
            <p className='text-xs font-medium text-muted-foreground'>
              {t('stepsHeading')}
            </p>
            <ScrollArea className='h-[60vh] pr-2'>
              <div className='min-w-0 break-words'>
                <StepTraceBody executionId={executionId} />
              </div>
            </ScrollArea>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
