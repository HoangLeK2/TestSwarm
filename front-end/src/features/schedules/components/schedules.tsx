'use client';

import { useEffect, useMemo, useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { enUS, vi } from 'date-fns/locale';
import {
  CalendarCheck2,
  CheckCircle2,
  Clock3,
  FileText,
  PauseCircle,
  Plus
} from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import type { ScheduleOut } from '../services/api';
import { useSchedules } from '../hooks/use-schedules';
import { useCampaigns } from '@/features/campaigns/hooks/use-campaigns';
import {
  isCampaignActiveExecution,
  type CampaignOut
} from '@/features/campaigns/types';
import { useScenarioTemplates } from '@/features/scenario-templates/hooks/use-scenario-templates';
import { useOrgScenarios } from '@/features/org-scenarios/hooks/use-org-scenarios';
import { Button } from '@/components/ui/button';
import { ScheduleFormDialog } from './schedule-form-dialog';
import {
  ScheduleCalendarPreview,
  type ScheduleCalendarPreviewItem
} from './schedule-calendar-preview';
import { ScheduleDetailPanel } from './schedule-detail-panel';
import Link from 'next/link';
import { ROUTES } from '@/config/routes';
import { Can } from '@/features/auth';
import { Badge } from '@/components/ui/badge';

export function Schedules() {
  const tList = useTranslations('schedulesFeature.list');
  const locale = useLocale();
  const { data: schedules, isLoading, error } = useSchedules();
  const { data: campaigns = [] } = useCampaigns();
  const data: ScheduleOut[] = useMemo(() => schedules ?? [], [schedules]);
  const hasTemplateTargets = data.some((s) => s.target_type === 'template');
  const hasOrgScenarioTargets = data.some(
    (s) => s.target_type === 'org_scenario'
  );
  const { data: templates = [] } = useScenarioTemplates(undefined, {
    enabled: hasTemplateTargets
  });
  const { data: orgScenarios = [] } = useOrgScenarios({
    enabled: hasOrgScenarioTargets
  });
  const campaignById = useMemo(
    () => new Map(campaigns.map((campaign) => [campaign.id, campaign])),
    [campaigns]
  );
  const templateById = useMemo(
    () => new Map(templates.map((template) => [template.id, template])),
    [templates]
  );
  const orgScenarioById = useMemo(
    () => new Map(orgScenarios.map((scenario) => [scenario.id, scenario])),
    [orgScenarios]
  );
  const enabledCount = useMemo(
    () => data.filter((schedule) => schedule.is_enabled).length,
    [data]
  );
  const pausedCount = Math.max(0, data.length - enabledCount);
  const nextRunLabel = useMemo(() => {
    const nextRun = data
      .filter((schedule) => schedule.is_enabled && schedule.next_run_at)
      .map((schedule) => new Date(schedule.next_run_at as string))
      .filter((date) => !Number.isNaN(date.getTime()))
      .sort((left, right) => left.getTime() - right.getTime())[0];

    if (!nextRun) return tList('feedbackNoNextRun');

    return formatDistanceToNow(nextRun, {
      addSuffix: true,
      locale: locale === 'vi' ? vi : enUS
    });
  }, [data, locale, tList]);
  const runningCampaigns = useMemo(
    () =>
      campaigns.filter((campaign) =>
        isCampaignActiveExecution(campaign.status)
      ),
    [campaigns]
  );
  const calendarSchedules = useMemo<ScheduleCalendarPreviewItem[]>(
    () =>
      data.map((schedule) => {
        const targetLabel =
          schedule.target_type === 'campaign'
            ? (campaignById.get(schedule.target_id ?? '')?.name ??
              tList('targetCampaign'))
            : schedule.target_type === 'template'
              ? (templateById.get(schedule.target_id ?? '')?.name ??
                tList('targetTemplate'))
              : schedule.target_type === 'org_scenario'
                ? (orgScenarioById.get(schedule.target_id ?? '')?.name ??
                  tList('targetOrgScenario'))
                : tList('targetFleet');

        return {
          id: schedule.id,
          name: schedule.name,
          cronExpression: schedule.cron_expression ?? '*/30 * * * *',
          timezone: schedule.timezone,
          targetLabel,
          isEnabled: Boolean(schedule.is_enabled)
        };
      }),
    [data, campaignById, orgScenarioById, templateById, tList]
  );

  const [createOpen, setCreateOpen] = useState(false);
  const [selectedScheduleId, setSelectedScheduleId] = useState<string | null>(
    null
  );
  const selectedSchedule = useMemo(
    () =>
      data.find((item) => item.id === selectedScheduleId) ?? data[0] ?? null,
    [data, selectedScheduleId]
  );
  const selectedCalendarItem = selectedSchedule
    ? calendarSchedules.find((item) => item.id === selectedSchedule.id)
    : null;

  useEffect(() => {
    if (!data.length) {
      setSelectedScheduleId(null);
      return;
    }
    if (
      !selectedScheduleId ||
      !data.some((item) => item.id === selectedScheduleId)
    ) {
      setSelectedScheduleId(data[0].id);
    }
  }, [data, selectedScheduleId]);

  const scheduleFeedback = [
    {
      icon: CalendarCheck2,
      label: tList('feedbackTotalLabel'),
      value: tList('feedbackCount', { count: data.length })
    },
    {
      icon: CheckCircle2,
      label: tList('feedbackEnabledLabel'),
      value: tList('feedbackCount', { count: enabledCount })
    },
    {
      icon: PauseCircle,
      label: tList('feedbackPausedLabel'),
      value: tList('feedbackCount', { count: pausedCount })
    },
    {
      icon: Clock3,
      label: tList('feedbackNextRunLabel'),
      value: nextRunLabel
    }
  ];

  const handleSelectSchedule = (scheduleId: string) => {
    setSelectedScheduleId(scheduleId);
  };

  return (
    <div className='space-y-6'>
      {runningCampaigns.length > 0 && (
        <div className='rounded-lg border border-emerald-500/25 bg-emerald-500/10 p-3'>
          <div className='flex flex-wrap items-center gap-2'>
            <Badge className='bg-emerald-600 text-[11px] text-white hover:bg-emerald-600'>
              {tList('runningCampaignsLabel', {
                count: runningCampaigns.length
              })}
            </Badge>
            {runningCampaigns.map((campaign: CampaignOut) => (
              <Button
                key={campaign.id}
                asChild
                size='sm'
                variant='outline'
                className='h-7 max-w-full px-2 text-xs'
              >
                <Link href={ROUTES.CAMPAIGNS.MONITOR(campaign.id)}>
                  <span className='truncate'>{campaign.name}</span>
                </Link>
              </Button>
            ))}
          </div>
        </div>
      )}

      {isLoading || error ? (
        <div>
          {isLoading && (
            <p className='text-sm text-muted-foreground'>{tList('loading')}</p>
          )}
          {error && (
            <p className='text-sm text-destructive'>{tList('loadError')}</p>
          )}
        </div>
      ) : (
        <>
          <section className='overflow-hidden rounded-xl border bg-card shadow-sm'>
            <div className='flex flex-wrap items-start justify-between gap-4 border-b bg-muted/20 p-4'>
              <div className='flex min-w-0 items-start gap-3'>
                <span className='mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl border bg-background text-primary shadow-sm'>
                  <CalendarCheck2 className='size-5' />
                </span>
                <div className='min-w-0'>
                  <h2 className='text-lg font-semibold tracking-tight text-foreground'>
                    {tList('guideTitle')}
                  </h2>
                  <p className='mt-1 max-w-3xl text-sm leading-6 text-muted-foreground'>
                    {tList('guideDescription')}
                  </p>
                </div>
              </div>
              <Can object='schedules' action='create'>
                <Button size='sm' onClick={() => setCreateOpen(true)}>
                  <Plus size={16} className='mr-1' />
                  {tList('guidePrimaryCta')}
                </Button>
              </Can>
            </div>
            <div className='grid gap-px bg-border sm:grid-cols-2 xl:grid-cols-4'>
              {scheduleFeedback.map((item) => {
                const Icon = item.icon;
                return (
                  <div
                    key={item.label}
                    className='flex min-w-0 items-center gap-3 bg-card px-4 py-3'
                    aria-label={`${item.label}: ${item.value}`}
                  >
                    <span className='flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground'>
                      <Icon className='size-4' />
                    </span>
                    <div className='min-w-0'>
                      <p className='text-xs text-muted-foreground'>
                        {item.label}
                      </p>
                      <p className='truncate text-sm font-semibold text-foreground'>
                        {item.value}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {!schedules?.length ? (
            <div className='rounded-xl border border-dashed border-border bg-muted/20 p-8 text-center'>
              <FileText className='mx-auto mb-4 size-10 text-muted-foreground/80' />
              <p className='text-sm font-medium text-foreground'>
                {tList('emptyTitle')}
              </p>
              <p className='mx-auto mt-1 max-w-md text-sm leading-6 text-muted-foreground'>
                {tList('emptyDescription')}
              </p>
              <div className='mt-5 flex flex-wrap justify-center gap-2'>
                <Can object='schedules' action='create'>
                  <Button size='sm' onClick={() => setCreateOpen(true)}>
                    <Plus size={16} className='mr-1' />
                    {tList('guidePrimaryCta')}
                  </Button>
                </Can>
                <Button asChild size='sm' variant='outline'>
                  <Link href={ROUTES.CAMPAIGNS.ROOT}>
                    {tList('quickStartGoCampaigns')}
                  </Link>
                </Button>
                <Button asChild size='sm' variant='ghost'>
                  <Link href={ROUTES.DEVICE_GROUPS.ROOT}>
                    {tList('quickStartGoDeviceGroups')}
                  </Link>
                </Button>
              </div>
            </div>
          ) : (
            <section className='overflow-hidden rounded-xl border bg-card shadow-sm'>
              <div className='grid items-start gap-px bg-border lg:grid-cols-[minmax(0,1fr)_20rem] 2xl:grid-cols-[minmax(0,1fr)_22rem]'>
                <div className='order-1 bg-card lg:sticky lg:top-4 lg:order-2 lg:self-start'>
                  <ScheduleDetailPanel
                    schedule={selectedSchedule}
                    targetLabel={selectedCalendarItem?.targetLabel ?? null}
                    onDeleted={() => setSelectedScheduleId(null)}
                  />
                </div>
                <div className='order-2 min-w-0 bg-card lg:order-1'>
                  <ScheduleCalendarPreview
                    schedules={calendarSchedules}
                    selectedScheduleId={selectedSchedule?.id ?? null}
                    onSelectSchedule={handleSelectSchedule}
                    className='min-w-0 border-0 shadow-none'
                  />
                </div>
              </div>
            </section>
          )}

          {createOpen && (
            <ScheduleFormDialog
              open={createOpen}
              onOpenChange={setCreateOpen}
              mode='create'
            />
          )}
        </>
      )}
    </div>
  );
}
