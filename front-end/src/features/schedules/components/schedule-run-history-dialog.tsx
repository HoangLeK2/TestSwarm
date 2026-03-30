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
import { useScheduleRuns } from '../hooks/use-schedules';

function statusVariant(status: string): 'secondary' | 'default' | 'outline' | 'destructive' {
  const s = status.toLowerCase();
  if (['failed', 'error', 'cancelled'].includes(s)) return 'destructive';
  if (['running', 'pending', 'queued'].includes(s)) return 'outline';
  if (['success', 'succeeded', 'completed', 'done'].includes(s)) return 'default';
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

  const headerStatus = useMemo(() => {
    if (!runs?.length) return null;
    const latest = runs[0]?.status ?? '';
    const v = statusVariant(latest);
    if (v === 'destructive') return <XCircle className='mr-2 size-4 text-red-600' />;
    if (v === 'default') return <CheckCircle className='mr-2 size-4 text-green-600' />;
    return <Clock className='mr-2 size-4' />;
  }, [runs]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='icon' variant='ghost' className='size-7' title={t('history')}>
          <History size={14} />
        </Button>
      </DialogTrigger>

      <DialogContent className='z-[1000] max-w-4xl max-h-[90vh] overflow-y-auto'>
        <DialogHeader>
          <DialogTitle className='flex items-center'>
            {headerStatus}
            {t('historyTitle', { name: scheduleName })}
          </DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <p className='text-sm text-muted-foreground pt-2'>{t('historyLoading')}</p>
        ) : !runs?.length ? (
          <p className='text-sm text-muted-foreground pt-2'>{t('historyEmpty')}</p>
        ) : (
          <div className='pt-2'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className='w-[120px]'>{t('runColStatus')}</TableHead>
                  <TableHead className='w-[180px]'>{t('runColStarted')}</TableHead>
                  <TableHead className='w-[180px]'>{t('runColFinished')}</TableHead>
                  <TableHead className='w-[110px]'>{t('runColDispatched')}</TableHead>
                  <TableHead className='w-[110px]'>{t('runColSucceeded')}</TableHead>
                  <TableHead className='w-[110px]'>{t('runColFailed')}</TableHead>
                  <TableHead>{t('runColError')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>
                      <Badge
                        variant={statusVariant(r.status)}
                        className='inline-flex items-center text-[11px]'
                      >
                        {r.status}
                      </Badge>
                    </TableCell>
                    <TableCell className='whitespace-nowrap text-[11px] text-muted-foreground'>
                      {r.started_at ? formatDistanceToNow(new Date(r.started_at), { addSuffix: true, locale: vi }) : '-'}
                    </TableCell>
                    <TableCell className='whitespace-nowrap text-[11px] text-muted-foreground'>
                      {r.finished_at
                        ? formatDistanceToNow(new Date(r.finished_at), { addSuffix: true, locale: vi })
                        : '-'}
                    </TableCell>
                    <TableCell className='text-[11px]'>{r.devices_dispatched}</TableCell>
                    <TableCell className='text-[11px] text-green-600'>{r.devices_succeeded}</TableCell>
                    <TableCell className='text-[11px] text-destructive'>{r.devices_failed}</TableCell>
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
    </Dialog>
  );
}

