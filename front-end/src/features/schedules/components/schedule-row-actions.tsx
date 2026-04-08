'use client';

import { useState } from 'react';
import { Play, Pencil, Power, Trash2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { Button } from '@/components/ui/button';
import { useToggleSchedule, useRunNowSchedule, useDeleteSchedule } from '../hooks/use-schedules';
import type { ScheduleOut } from '../services/api';
import { ScheduleFormDialog } from './schedule-form-dialog';
import { ScheduleRunHistoryDialog } from './schedule-run-history-dialog';

export function ScheduleRowActions({ schedule }: { schedule: ScheduleOut }) {
  const t = useTranslations('schedulesFeature.actions');
  const toggleMutation = useToggleSchedule();
  const runNowMutation = useRunNowSchedule();
  const deleteMutation = useDeleteSchedule();

  const [editOpen, setEditOpen] = useState(false);

  const isPending = toggleMutation.isPending || runNowMutation.isPending || deleteMutation.isPending;

  const handleToggle = () => {
    toggleMutation.mutate(
      { scheduleId: schedule.id, enabled: !schedule.is_enabled },
      {
        onError: (err: unknown) => toast.error(formatFarmApiError(err, t('toggleFailed')))
      }
    );
  };

  const handleRunNow = () => {
    runNowMutation.mutate(schedule.id, {
      onError: (err: unknown) => toast.error(formatFarmApiError(err, t('runNowFailed')))
    });
  };

  const handleDelete = () => {
    const ok = window.confirm(t('deleteConfirm', { name: schedule.name }));
    if (!ok) return;
    deleteMutation.mutate(schedule.id, {
      onSuccess: () => toast.success(t('deleteSuccess')),
      onError: (err: unknown) => toast.error(formatFarmApiError(err, t('deleteFailed')))
    });
  };

  return (
    <div className='flex items-center justify-center gap-1'>
      <ScheduleRunHistoryDialog scheduleId={schedule.id} scheduleName={schedule.name} />

      <Button
        size='icon'
        variant='ghost'
        className='size-7 text-amber-600 hover:text-amber-600'
        disabled={runNowMutation.isPending}
        onClick={handleRunNow}
        title={t('runNow')}
      >
        <Play size={14} />
      </Button>

      <Button
        size='icon'
        variant='ghost'
        className={`size-7 ${schedule.is_enabled ? 'text-green-600 hover:text-green-600' : 'text-muted-foreground hover:text-muted-foreground'}`}
        disabled={toggleMutation.isPending}
        onClick={handleToggle}
        title={schedule.is_enabled ? t('disable') : t('enable')}
      >
        <Power size={14} />
      </Button>

      <Button
        size='icon'
        variant='ghost'
        className='size-7'
        disabled={isPending}
        onClick={() => setEditOpen(true)}
        title={t('edit')}
      >
        <Pencil size={14} />
      </Button>

      <Button
        size='icon'
        variant='ghost'
        className='size-7 text-destructive hover:text-destructive'
        disabled={deleteMutation.isPending}
        onClick={handleDelete}
        title={t('delete')}
      >
        <Trash2 size={14} />
      </Button>

      {editOpen && (
        <ScheduleFormDialog
          open={editOpen}
          onOpenChange={setEditOpen}
          mode='edit'
          schedule={schedule}
        />
      )}
    </div>
  );
}

