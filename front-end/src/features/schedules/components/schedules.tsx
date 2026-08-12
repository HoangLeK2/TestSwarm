'use client';

import { useMemo, useState } from 'react';
import { Plus } from 'lucide-react';
import { useTranslations } from 'next-intl';
import type { ScheduleOut } from '../services/api';
import { useSchedules } from '../hooks/use-schedules';
import { useCampaigns } from '@/features/campaigns/hooks/use-campaigns';
import {
  isCampaignActiveExecution,
  type CampaignOut
} from '@/features/campaigns/types';
import { useScenarioTemplates } from '@/features/scenario-templates/hooks/use-scenario-templates';
import { Button } from '@/components/ui/button';
import { ScheduleFormDialog } from './schedule-form-dialog';
import {
  ScheduleCalendarPreview,
  type ScheduleCalendarPreviewItem
} from './schedule-calendar-preview';
import { FileText } from 'lucide-react';
import Link from 'next/link';
import { ROUTES } from '@/config/routes';
import { Can } from '@/features/auth';
import { Badge } from '@/components/ui/badge';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';

export function Schedules() {
  const tList = useTranslations('schedulesFeature.list');
  const { data: schedules, isLoading, error } = useSchedules();
  const { data: campaigns = [] } = useCampaigns();
  const perms = useResourcePermissions('schedules');

  const data: ScheduleOut[] = useMemo(() => schedules ?? [], [schedules]);
  const hasTemplateTargets = data.some((s) => s.target_type === 'template');
  const { data: templates = [] } = useScenarioTemplates(undefined, {
    enabled: hasTemplateTargets
  });
  const campaignById = useMemo(
    () => new Map(campaigns.map((campaign) => [campaign.id, campaign])),
    [campaigns]
  );
  const templateById = useMemo(
    () => new Map(templates.map((template) => [template.id, template])),
    [templates]
  );
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
    [data, campaignById, templateById, tList]
  );

  const [createOpen, setCreateOpen] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<ScheduleOut | null>(
    null
  );

  const handleSelectSchedule = (scheduleId: string) => {
    const schedule = data.find((item) => item.id === scheduleId);
    if (!schedule) return;
    setEditingSchedule(schedule);
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
          {!!schedules?.length && (
            <div className='flex flex-wrap items-center justify-between gap-3'>
              <p className='text-muted-foreground'>
                <span className='font-medium text-foreground'>
                  {schedules?.length ?? 0}
                </span>{' '}
                {tList('countLabel')}
              </p>
              <Can object='schedules' action='create'>
                <Button size='sm' onClick={() => setCreateOpen(true)}>
                  <Plus size={16} className='mr-1' />
                  {tList('trigger')}
                </Button>
              </Can>
            </div>
          )}

          {!schedules?.length ? (
            <div className='rounded-xl border border-dashed border-border bg-muted/20 p-16 text-center'>
              <FileText className='mx-auto mb-4 size-12 text-muted-foreground/80' />
              <p className='text-sm font-medium text-foreground'>
                {tList('emptyTitle')}
              </p>
              <p className='mt-1 text-sm text-muted-foreground'>
                {tList('emptyDescription')}
              </p>
              <div className='mx-auto mt-6 max-w-[42rem] rounded-lg border border-border/60 bg-background/50 p-4 text-center'>
                <p className='text-xs font-semibold text-foreground'>
                  {tList('quickStartTitle')}
                </p>
                <ol className='mx-auto mt-2 list-decimal space-y-1 pl-4 text-left text-xs text-muted-foreground'>
                  <li>{tList('quickStartStep1')}</li>
                  <li>{tList('quickStartStep2')}</li>
                  <li>{tList('quickStartStep3')}</li>
                </ol>
                <div className='mt-3 flex flex-wrap justify-center gap-2'>
                  <Button asChild size='sm' variant='outline'>
                    <Link href={ROUTES.DEVICE_GROUPS.ROOT}>
                      {tList('quickStartGoDeviceGroups')}
                    </Link>
                  </Button>
                  <Button asChild size='sm' variant='outline'>
                    <Link href={ROUTES.CAMPAIGNS.ROOT}>
                      {tList('quickStartGoCampaigns')}
                    </Link>
                  </Button>
                  <Can object='schedules' action='create'>
                    <Button size='sm' onClick={() => setCreateOpen(true)}>
                      <Plus size={16} className='mr-1' />
                      {tList('trigger')}
                    </Button>
                  </Can>
                </div>
              </div>
            </div>
          ) : (
            <ScheduleCalendarPreview
              schedules={calendarSchedules}
              onSelectSchedule={
                perms.canUpdate ? handleSelectSchedule : undefined
              }
            />
          )}

          {createOpen && (
            <ScheduleFormDialog
              open={createOpen}
              onOpenChange={setCreateOpen}
              mode='create'
            />
          )}

          {editingSchedule && (
            <ScheduleFormDialog
              open={Boolean(editingSchedule)}
              onOpenChange={(nextOpen) => {
                if (!nextOpen) setEditingSchedule(null);
              }}
              mode='edit'
              schedule={editingSchedule}
            />
          )}
        </>
      )}
    </div>
  );
}
