'use client';

import { useMemo, useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { vi } from 'date-fns/locale';
import { Clock, History, XCircle, CheckCircle } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { useScheduleRun, useScheduleRuns } from '../hooks/use-schedules';

function statusVariant(
  status: string
): 'secondary' | 'default' | 'outline' | 'destructive' {
  const s = status.toLowerCase();
  if (['failed', 'error', 'cancelled'].includes(s)) return 'destructive';
  if (['running', 'pending', 'queued'].includes(s)) return 'outline';
  if (['success', 'succeeded', 'completed', 'done'].includes(s))
    return 'default';
  return 'secondary';
}

export function ScheduleRunHistoryDialog({
  scheduleId,
  scheduleName
}: {
  scheduleId: string;
  scheduleName: string;
}) {
  const t = useTranslations('schedulesFeature.list');
  const [open, setOpen] = useState(false);

  const { data: runs, isLoading } = useScheduleRuns(scheduleId, open);

  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const {
    data: runDetail,
    isLoading: isDetailLoading,
    error: detailError
  } = useScheduleRun(scheduleId, selectedRunId);

  const headerStatus = useMemo(() => {
    if (!runs?.length) return null;
    const latest = runs[0]?.status ?? '';
    const v = statusVariant(latest);
    if (v === 'destructive')
      return <XCircle className='mr-2 size-4 text-red-600' />;
    if (v === 'default')
      return <CheckCircle className='mr-2 size-4 text-green-600' />;
    return <Clock className='mr-2 size-4' />;
  }, [runs]);

  const statusLabel = (status: string) => {
    const s = status.toLowerCase();
    if (s === 'pending' || s === 'queued' || s === 'running')
      return t('statusRunning');
    if (['success', 'succeeded', 'completed', 'done'].includes(s))
      return t('statusCompleted');
    if (['failed', 'error', 'cancelled', 'canceled'].includes(s))
      return t('statusFailed');
    return status;
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          size='icon'
          variant='ghost'
          className='size-7'
          title={t('history')}
        >
          <History size={14} />
        </Button>
      </DialogTrigger>

      <DialogContent className='z-[1000] max-h-[90vh] max-w-4xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle className='flex items-center'>
            {headerStatus}
            {t('historyTitle', { name: scheduleName })}
          </DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <p className='pt-2 text-sm text-muted-foreground'>
            {t('historyLoading')}
          </p>
        ) : !runs?.length ? (
          <p className='pt-2 text-sm text-muted-foreground'>
            {t('historyEmpty')}
          </p>
        ) : (
          <div className='pt-2'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className='w-[120px]'>
                    {t('runColStatus')}
                  </TableHead>
                  <TableHead className='w-[180px]'>
                    {t('runColStarted')}
                  </TableHead>
                  <TableHead className='w-[180px]'>
                    {t('runColFinished')}
                  </TableHead>
                  <TableHead className='w-[110px]'>
                    {t('runColDispatched')}
                  </TableHead>
                  <TableHead className='w-[110px]'>
                    {t('runColSucceeded')}
                  </TableHead>
                  <TableHead className='w-[110px]'>
                    {t('runColFailed')}
                  </TableHead>
                  <TableHead>{t('runColError')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((r) => (
                  <TableRow
                    key={r.id}
                    className='cursor-pointer'
                    onClick={() => {
                      setSelectedRunId(r.id);
                      setDetailOpen(true);
                    }}
                  >
                    <TableCell>
                      <Badge
                        variant={statusVariant(r.status)}
                        className='inline-flex items-center text-[11px]'
                      >
                        {statusLabel(r.status)}
                      </Badge>
                    </TableCell>
                    <TableCell className='whitespace-nowrap text-[11px] text-muted-foreground'>
                      {r.started_at
                        ? formatDistanceToNow(new Date(r.started_at), {
                            addSuffix: true,
                            locale: vi
                          })
                        : '-'}
                    </TableCell>
                    <TableCell className='whitespace-nowrap text-[11px] text-muted-foreground'>
                      {r.finished_at
                        ? formatDistanceToNow(new Date(r.finished_at), {
                            addSuffix: true,
                            locale: vi
                          })
                        : '-'}
                    </TableCell>
                    <TableCell className='text-[11px]'>
                      {r.devices_dispatched}
                    </TableCell>
                    <TableCell className='text-[11px] text-green-600'>
                      {r.devices_succeeded}
                    </TableCell>
                    <TableCell className='text-[11px] text-destructive'>
                      {r.devices_failed}
                    </TableCell>
                    <TableCell className='max-w-[360px]'>
                      <span className='block truncate text-[11px] text-muted-foreground'>
                        {r.error_message ?? '-'}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </DialogContent>

      <Dialog
        open={detailOpen}
        onOpenChange={(v) => {
          setDetailOpen(v);
          if (!v) setSelectedRunId(null);
        }}
      >
        <DialogContent className='z-[1100] max-h-[90vh] max-w-3xl overflow-y-auto'>
          <DialogHeader>
            <DialogTitle>
              {t('detailsTitle', { name: scheduleName })}
            </DialogTitle>
          </DialogHeader>

          {isDetailLoading ? (
            <p className='pt-2 text-sm text-muted-foreground'>
              {t('detailsLoading')}
            </p>
          ) : detailError ? (
            <p className='pt-2 text-sm text-destructive'>{t('detailsError')}</p>
          ) : !runDetail ? (
            <p className='pt-2 text-sm text-muted-foreground'>
              {t('detailsEmpty')}
            </p>
          ) : (
            <div className='space-y-4 pt-2'>
              <div className='flex items-center justify-between gap-3'>
                <Badge
                  variant={statusVariant(runDetail.status)}
                  className='inline-flex items-center text-[11px]'
                >
                  {runDetail.status}
                </Badge>
                <span className='font-mono text-[11px] text-muted-foreground'>
                  {runDetail.id}
                </span>
              </div>

              <div className='grid grid-cols-2 gap-3'>
                <div className='space-y-1'>
                  <div className='text-xs text-muted-foreground'>
                    {t('runColStarted')}
                  </div>
                  <div className='text-[11px]'>
                    {runDetail.started_at
                      ? formatDistanceToNow(new Date(runDetail.started_at), {
                          addSuffix: true,
                          locale: vi
                        })
                      : '-'}
                  </div>
                </div>
                <div className='space-y-1'>
                  <div className='text-xs text-muted-foreground'>
                    {t('runColFinished')}
                  </div>
                  <div className='text-[11px]'>
                    {runDetail.finished_at
                      ? formatDistanceToNow(new Date(runDetail.finished_at), {
                          addSuffix: true,
                          locale: vi
                        })
                      : '-'}
                  </div>
                </div>
              </div>

              <div className='grid grid-cols-3 gap-3'>
                <div className='space-y-1'>
                  <div className='text-xs text-muted-foreground'>
                    {t('runColDispatched')}
                  </div>
                  <div className='text-[11px]'>
                    {runDetail.devices_dispatched}
                  </div>
                </div>
                <div className='space-y-1'>
                  <div className='text-xs text-muted-foreground'>
                    {t('runColSucceeded')}
                  </div>
                  <div className='text-[11px] text-green-600'>
                    {runDetail.devices_succeeded}
                  </div>
                </div>
                <div className='space-y-1'>
                  <div className='text-xs text-muted-foreground'>
                    {t('runColFailed')}
                  </div>
                  <div className='text-[11px] text-destructive'>
                    {runDetail.devices_failed}
                  </div>
                </div>
              </div>

              <div className='space-y-1'>
                <div className='text-xs text-muted-foreground'>
                  {t('runColError')}
                </div>
                <div className='whitespace-pre-wrap rounded border bg-muted/10 p-3 text-[11px] text-muted-foreground'>
                  {runDetail.error_message ?? '-'}
                </div>
              </div>

              <div className='space-y-1'>
                <div className='text-xs text-muted-foreground'>
                  {t('taskIds')}
                </div>
                {runDetail.task_ids?.length ? (
                  <div className='rounded border bg-muted/10 p-3'>
                    <ul className='space-y-1'>
                      {runDetail.task_ids.map((id) => (
                        <li
                          key={id}
                          className='truncate font-mono text-[11px] text-muted-foreground'
                        >
                          {id}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <p className='text-[11px] text-muted-foreground'>-</p>
                )}
              </div>

              <div className='flex justify-end pt-2'>
                <Button size='sm' onClick={() => setDetailOpen(false)}>
                  {t('close')}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </Dialog>
  );
}
