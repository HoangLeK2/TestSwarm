'use client';

import { useEffect, useMemo, useState } from 'react';
import { ImageIcon, Loader2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { ExecutionOut } from '../../types';
import {
  useCampaignExecutionHistory,
  useExecutionArtifacts
} from '../../hooks/use-campaigns';
import {
  artifactIsFailShot,
  groupArtifactsByDevice,
  uniqueDeviceSerials,
  type DeviceFilter,
  type ResolvedMonitorArtifact
} from '../../lib/artifact-panel-model';
import {
  artifactIsImage,
  resolvedArtifactHref
} from '../../lib/artifact-monitor-utils';
import {
  executionStatusLabel,
  formatTs
} from './dlq-run-summary';
import { MonitorSectionHeader } from './monitor-section-header';
import { ArtifactMonitorTile } from './artifact-tile';

interface Props {
  campaignId: string;
  pollAggressive?: boolean;
  variant?: 'default' | 'split';
}

function artifactTypeLabel(
  artifactType: string,
  t: (key: string) => string
): string {
  switch (artifactType) {
    case 'fail.screenshot':
      return t('monitorArtifactTypeFailScreenshot');
    case 'screenshot_pre':
      return t('monitorDlqArtifactScreenshotPre');
    case 'screenshot_post':
      return t('monitorDlqArtifactScreenshotPost');
    case 'content_screenshot':
      return t('monitorArtifactTypeContentScreenshot');
    default:
      return artifactType;
  }
}

function buildResolvedArtifact(
  artifact: ResolvedMonitorArtifact['artifact'],
  href: string,
  t: (key: string, values?: Record<string, string | number>) => string,
  idx: number
): ResolvedMonitorArtifact {
  const deviceLabel =
    artifact.device_serial?.trim() || t('monitorArtifactDeviceUnknown');
  const typeLabel = artifactTypeLabel(artifact.artifact_type, t);
  let subtitle = typeLabel;
  const stepNumber =
    artifact.step_index != null ? artifact.step_index + 1 : null;
  if (stepNumber != null) {
    const stepType = artifact.step_type?.trim();
    subtitle = stepType
      ? t('monitorArtifactStepLabel', { index: stepNumber, type: stepType })
      : t('monitorArtifactStepIndexLabel', {
          index: stepNumber,
          type: typeLabel
        });
  }
  const message = artifact.message?.trim();
  if (message && artifactIsFailShot(artifact)) {
    subtitle = `${subtitle} - ${message}`;
  }
  const timeLabel = artifact.created_at ? formatTs(artifact.created_at) : '';
  return {
    key: `${artifact.execution_id}-${artifact.artifact_type}-${artifact.step_index ?? 'x'}-${idx}`,
    artifact,
    href,
    deviceLabel,
    subtitle,
    isFail: artifactIsFailShot(artifact),
    stepNumber,
    timeLabel
  };
}

function executionStatusTone(
  status: string
): 'default' | 'secondary' | 'destructive' | 'outline' {
  const normalized = status.toLowerCase();
  if (normalized.includes('fail')) return 'destructive';
  if (normalized.includes('run')) return 'default';
  if (normalized.includes('complete')) return 'secondary';
  return 'outline';
}

function sortExecutionsByRecency(executions: ExecutionOut[]): ExecutionOut[] {
  return [...executions].sort((a, b) => {
    const aTime = Date.parse(
      a.finished_at ?? a.started_at ?? a.created_at ?? ''
    );
    const bTime = Date.parse(
      b.finished_at ?? b.started_at ?? b.created_at ?? ''
    );
    return (Number.isNaN(bTime) ? 0 : bTime) - (Number.isNaN(aTime) ? 0 : aTime);
  });
}

function RunHistoryRow({
  execution,
  active,
  onSelect,
  t
}: {
  execution: ExecutionOut;
  active: boolean;
  onSelect: () => void;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  return (
    <button
      type='button'
      onClick={onSelect}
      className={cn(
        'flex w-full min-w-0 flex-col gap-2 rounded-lg border px-3 py-2 text-left text-sm transition sm:flex-row sm:items-center sm:justify-between',
        active
          ? 'border-primary/40 bg-primary/[0.06]'
          : 'border-border/70 hover:border-primary/20 hover:bg-muted/40'
      )}
    >
      <span
        className={cn(
          'min-w-0 truncate text-xs leading-snug sm:text-sm',
          active && 'font-medium'
        )}
      >
        {formatTs(
          execution.finished_at ??
            execution.started_at ??
            execution.created_at
        )}
      </span>
      <Badge
        variant={executionStatusTone(execution.status)}
        className='w-fit sm:shrink-0'
      >
        {executionStatusLabel(execution.status, t)}
      </Badge>
    </button>
  );
}

function ArtifactShotRow({
  item,
  active,
  hideDeviceLabel,
  onSelect
}: {
  item: ResolvedMonitorArtifact;
  active: boolean;
  hideDeviceLabel: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type='button'
      onClick={onSelect}
      className={cn(
        'flex w-full min-w-0 items-start gap-2 rounded-lg border px-3 py-2 text-left text-sm transition',
        active
          ? 'border-primary/40 bg-primary/[0.06]'
          : 'border-border/70 hover:border-primary/20 hover:bg-muted/40'
      )}
    >
      <div className='flex min-w-0 flex-1 flex-col gap-1'>
        <div className='flex flex-wrap items-center gap-1.5'>
          {item.stepNumber != null ? (
            <Badge
              variant='secondary'
              className='h-5 px-1.5 text-[10px] font-bold tabular-nums'
            >
              B{item.stepNumber}
            </Badge>
          ) : null}
          {item.isFail ? (
            <Badge
              variant='destructive'
              className='h-5 px-1.5 text-[10px] font-bold'
            >
              !
            </Badge>
          ) : null}
          {!hideDeviceLabel ? (
            <span className='truncate text-xs font-semibold'>
              {item.deviceLabel}
            </span>
          ) : null}
        </div>
        <p className='text-[11px] leading-snug text-muted-foreground'>
          {item.subtitle}
        </p>
        {item.timeLabel ? (
          <p className='text-[10px] text-muted-foreground'>{item.timeLabel}</p>
        ) : null}
      </div>
      <ImageIcon
        size={16}
        className='mt-0.5 shrink-0 text-muted-foreground'
        aria-hidden
      />
    </button>
  );
}

function DeviceFilterChips({
  devices,
  allCount,
  deviceFilter,
  runArtifacts,
  onChange,
  t
}: {
  devices: string[];
  allCount: number;
  deviceFilter: DeviceFilter;
  runArtifacts: ResolvedMonitorArtifact[];
  onChange: (value: DeviceFilter) => void;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  return (
    <div className='flex flex-wrap gap-2'>
      <Button
        type='button'
        size='sm'
        variant={deviceFilter === 'all' ? 'default' : 'outline'}
        className='h-7 gap-1.5 px-2.5 text-xs'
        onClick={() => onChange('all')}
      >
        {t('monitorArtifactFilterAllDevices')}
        <Badge
          variant={deviceFilter === 'all' ? 'secondary' : 'outline'}
          className='h-4 min-w-4 px-1 text-[10px] tabular-nums'
        >
          {allCount}
        </Badge>
      </Button>
      {devices.map((device) => {
        const count = runArtifacts.filter((a) => a.deviceLabel === device).length;
        return (
          <Button
            key={device}
            type='button'
            size='sm'
            variant={deviceFilter === device ? 'default' : 'outline'}
            className='h-7 gap-1.5 px-2.5 text-xs font-mono'
            onClick={() => onChange(device)}
          >
            {device}
            <Badge
              variant={deviceFilter === device ? 'secondary' : 'outline'}
              className='h-4 min-w-4 px-1 text-[10px] tabular-nums'
            >
              {count}
            </Badge>
          </Button>
        );
      })}
    </div>
  );
}

export function ArtifactPanel({
  campaignId,
  pollAggressive: _pollAggressive = true,
  variant = 'default'
}: Props) {
  const split = variant === 'split';
  const t = useTranslations('campaignsFeature.list');
  const { data: executions = [], isLoading: executionsLoading } =
    useCampaignExecutionHistory(campaignId, true, _pollAggressive);

  const sortedExecutions = useMemo(
    () => sortExecutionsByRecency(executions),
    [executions]
  );

  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(
    null
  );
  const [selectedArtifactKey, setSelectedArtifactKey] = useState<string | null>(
    null
  );
  const [deviceFilter, setDeviceFilter] = useState<DeviceFilter>('all');

  const {
    data: rawArtifacts = [],
    isLoading: artifactsLoading,
    isFetching: artifactsFetching
  } = useExecutionArtifacts(selectedExecutionId, Boolean(selectedExecutionId), false);

  useEffect(() => {
    setDeviceFilter('all');
    setSelectedArtifactKey(null);
  }, [selectedExecutionId]);

  const runArtifacts = useMemo(() => {
    return rawArtifacts
      .map((artifact, idx) => {
        const href = resolvedArtifactHref(artifact);
        if (!href || !artifactIsImage(artifact, href)) return null;
        return buildResolvedArtifact(artifact, href, t, idx);
      })
      .filter((item): item is ResolvedMonitorArtifact => item != null);
  }, [rawArtifacts, t]);

  const filteredArtifacts = useMemo(() => {
    if (deviceFilter === 'all') return runArtifacts;
    return runArtifacts.filter((item) => item.deviceLabel === deviceFilter);
  }, [runArtifacts, deviceFilter]);

  const grouped = useMemo(
    () => groupArtifactsByDevice(runArtifacts, deviceFilter),
    [runArtifacts, deviceFilter]
  );

  const devices = useMemo(
    () => uniqueDeviceSerials(runArtifacts),
    [runArtifacts]
  );

  const selectedArtifact =
    filteredArtifacts.find((item) => item.key === selectedArtifactKey) ?? null;

  const isLoading = executionsLoading;
  const artifactsBusy =
    Boolean(selectedExecutionId) && (artifactsLoading || artifactsFetching);

  useEffect(() => {
    if (artifactsBusy || filteredArtifacts.length === 0) return;
    setSelectedArtifactKey((current) => {
      if (current && filteredArtifacts.some((item) => item.key === current)) {
        return current;
      }
      return filteredArtifacts[0]!.key;
    });
  }, [selectedExecutionId, artifactsBusy, filteredArtifacts]);

  return (
    <section className='min-w-0 px-4 py-5 sm:px-5'>
      <MonitorSectionHeader
        icon={<ImageIcon size={20} />}
        title={t('monitorArtifactTitle')}
        hint={t('monitorArtifactDescription')}
        count={selectedArtifact ? 1 : filteredArtifacts.length}
        countVariant={filteredArtifacts.length > 0 ? 'default' : 'secondary'}
      />

      {executions.length > 0 ? (
        <div className='mt-4 space-y-2'>
          <p className='text-[11px] font-medium uppercase tracking-wide text-muted-foreground'>
            {t('monitorArtifactRunHistoryLabel')}
          </p>
          <div className='max-h-56 space-y-1.5 overflow-y-auto pr-1'>
            {sortedExecutions.map((execution) => (
              <RunHistoryRow
                key={execution.id}
                execution={execution}
                active={execution.id === selectedExecutionId}
                onSelect={() => setSelectedExecutionId(execution.id)}
                t={t}
              />
            ))}
          </div>
        </div>
      ) : null}

      {!selectedExecutionId && !isLoading && executions.length > 0 ? (
        <p className='mt-4 rounded-lg border border-dashed px-3 py-4 text-center text-sm text-muted-foreground'>
          {t('monitorArtifactSelectRunHint')}
        </p>
      ) : null}

      {selectedExecutionId && artifactsBusy && runArtifacts.length === 0 ? (
        <p className='mt-4 flex items-center gap-2 text-sm text-muted-foreground'>
          <Loader2 size={16} className='animate-spin' />
          {t('monitorArtifactLoading')}
        </p>
      ) : null}

      {selectedExecutionId && !artifactsBusy && runArtifacts.length === 0 ? (
        <p className='mt-4 text-sm text-muted-foreground'>
          {t('monitorArtifactEmpty')}
        </p>
      ) : null}

      {runArtifacts.length > 0 ? (
        <div className='mt-4 space-y-2'>
          <p className='text-[11px] font-medium uppercase tracking-wide text-muted-foreground'>
            {t('monitorArtifactFilterDevice')}
          </p>
          <DeviceFilterChips
            devices={devices}
            allCount={runArtifacts.length}
            deviceFilter={deviceFilter}
            runArtifacts={runArtifacts}
            onChange={setDeviceFilter}
            t={t}
          />
        </div>
      ) : null}

      {isLoading ? (
        <p className='mt-4 flex items-center gap-2 text-sm text-muted-foreground'>
          <Loader2 size={16} className='animate-spin' />
          {t('monitorArtifactLoading')}
        </p>
      ) : null}

      {!isLoading && executions.length === 0 ? (
        <p className='mt-4 text-sm text-muted-foreground'>
          {t('monitorArtifactNoRuns')}
        </p>
      ) : null}

      {!artifactsBusy && grouped.length > 0 ? (
        <div className='mt-4 space-y-5'>
          {grouped.map((group) => (
            <div key={group.device}>
              <div className='mb-2 flex items-center justify-between gap-2'>
                <p className='font-mono text-sm font-semibold'>{group.device}</p>
                <span className='text-xs tabular-nums text-muted-foreground'>
                  {t('monitorArtifactGroupShotCount', {
                    count: group.shots.length
                  })}
                </span>
              </div>
              <div className='space-y-1.5'>
                {group.shots.map((item) => (
                  <ArtifactShotRow
                    key={item.key}
                    item={item}
                    active={item.key === selectedArtifactKey}
                    hideDeviceLabel={split}
                    onSelect={() => setSelectedArtifactKey(item.key)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {selectedArtifact ? (
        <div className='mt-4'>
          <ArtifactMonitorTile
            artifact={selectedArtifact.artifact}
            href={selectedArtifact.href}
            label={`${selectedArtifact.deviceLabel} · ${selectedArtifact.subtitle}`}
            deviceLabel={selectedArtifact.deviceLabel}
            subtitle={selectedArtifact.subtitle}
            stepNumber={selectedArtifact.stepNumber}
            isFail={selectedArtifact.isFail}
            timeLabel={selectedArtifact.timeLabel}
            hideDeviceLabel={split}
            compact={split}
          />
        </div>
      ) : selectedExecutionId && !artifactsBusy && filteredArtifacts.length > 0 ? (
        <p className='mt-4 rounded-lg border border-dashed px-3 py-4 text-center text-sm text-muted-foreground'>
          {t('monitorArtifactSelectShotHint')}
        </p>
      ) : null}
    </section>
  );
}
