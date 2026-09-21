'use client';

import { useState } from 'react';
import {
  History,
  MoreHorizontal,
  Play,
  Pencil,
  Power,
  Trash2
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import {
  useToggleSchedule,
  useRunNowSchedule,
  useDeleteSchedule
} from '../hooks/use-schedules';
import type { ScheduleOut } from '../services/api';
import { ScheduleFormDialog } from './schedule-form-dialog';
import { ScheduleRunHistoryDialog } from './schedule-run-history-dialog';
import { useConfirm } from '@/providers/modal-provider';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';

export function ScheduleRowActions({ schedule }: { schedule: ScheduleOut }) {
  const t = useTranslations('schedulesFeature.actions');
  const tCommon = useTranslations('common');
  const confirm = useConfirm();
  const toggleMutation = useToggleSchedule();
  const runNowMutation = useRunNowSchedule();
  const deleteMutation = useDeleteSchedule();
  const perms = useResourcePermissions('schedules');

  const [editOpen, setEditOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  const isPending =
    toggleMutation.isPending ||
    runNowMutation.isPending ||
    deleteMutation.isPending;

  const handleToggle = () => {
    toggleMutation.mutate(
      { scheduleId: schedule.id, enabled: !schedule.is_enabled },
      {
        onError: (err: unknown) =>
          toast.error(formatFarmApiError(err, t('toggleFailed')))
      }
    );
  };

  const handleRunNow = () => {
    runNowMutation.mutate(schedule.id, {
      onSuccess: () => toast.success(t('runNowSuccess')),
      onError: (err: unknown) =>
        toast.error(formatFarmApiError(err, t('runNowFailed')))
    });
  };

  const handleDelete = () => {
    void (async () => {
      const ok = await confirm({
        title: t('deleteConfirmTitle', { name: schedule.name }),
        description: t('deleteConfirmDescription'),
        confirmText: t('deleteConfirmAction'),
        cancelText: tCommon('cancel'),
        confirmVariant: 'destructive',
        zIndex: 10_000
      });
      if (!ok) return;
      deleteMutation.mutate(schedule.id, {
        onSuccess: () =>
          toast.success(t('deleteSuccess', { name: schedule.name })),
        onError: (err: unknown) =>
          toast.error(formatFarmApiError(err, t('deleteFailed')))
      });
    })();
  };

  return (
    <div className='flex items-center justify-end gap-1 whitespace-nowrap'>
      {perms.canExecute ? (
        <Button
          size='sm'
          variant='outline'
          className='h-8 gap-1 px-2 text-xs text-amber-600 hover:text-amber-600'
          disabled={runNowMutation.isPending}
          onClick={handleRunNow}
          title={t('runNowSchedule', { name: schedule.name })}
          aria-label={t('runNowSchedule', { name: schedule.name })}
        >
          <Play size={14} />
          <span>{t('runNow')}</span>
        </Button>
      ) : null}

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size='icon'
            variant='ghost'
            className='size-8'
            disabled={isPending}
            aria-label={t('moreActions')}
            title={t('moreActions')}
          >
            <MoreHorizontal className='size-4' />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align='end' className='w-44'>
          <DropdownMenuItem
            className='gap-2'
            onClick={() => setHistoryOpen(true)}
          >
            <History className='size-4' />
            {t('history')}
          </DropdownMenuItem>

          {perms.canUpdate ? (
            <>
              <DropdownMenuItem className='gap-2' onClick={handleToggle}>
                <Power className='size-4' />
                {schedule.is_enabled ? t('disableShort') : t('enableShort')}
              </DropdownMenuItem>
              <DropdownMenuItem
                className='gap-2'
                onClick={() => setEditOpen(true)}
              >
                <Pencil className='size-4' />
                {t('edit')}
              </DropdownMenuItem>
            </>
          ) : null}

          {perms.canDelete ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className='gap-2 text-destructive focus:text-destructive'
                onClick={handleDelete}
                variant='destructive'
              >
                <Trash2 className='size-4' />
                {t('delete')}
              </DropdownMenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>

      <ScheduleRunHistoryDialog
        scheduleId={schedule.id}
        scheduleName={schedule.name}
        open={historyOpen}
        onOpenChange={setHistoryOpen}
      />

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
