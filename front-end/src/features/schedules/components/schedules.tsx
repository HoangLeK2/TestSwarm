'use client';

import { useMemo, useState } from 'react';
import { Plus } from 'lucide-react';
import { useTranslations } from 'next-intl';
import type { ScheduleOut } from '../services/api';
import { useSchedules } from '../hooks/use-schedules';
import { DataTable } from '@/components/ui/table/data-table';
import { useDataTable } from '@/hooks/use-data-table';
import { Button } from '@/components/ui/button';
import { ScheduleFormDialog } from './schedule-form-dialog';
import { getScheduleColumns } from './schedule-columns';
import { FileText } from 'lucide-react';
import Link from 'next/link';
import { ROUTES } from '@/config/routes';

export function Schedules() {
  const tList = useTranslations('schedulesFeature.list');
  const tCron = useTranslations('schedulesFeature.cronBuilder');
  const { data: schedules, isLoading, error } = useSchedules();

  const data: ScheduleOut[] = schedules ?? [];
  const columns = useMemo(
    () => getScheduleColumns(tList, tCron),
    [tList, tCron]
  );

  const { table } = useDataTable<ScheduleOut>({
    data,
    columns,
    pageCount: 1
  });

  const [createOpen, setCreateOpen] = useState(false);

  return (
    <div className='space-y-6'>
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
              <Button size='sm' onClick={() => setCreateOpen(true)}>
                <Plus size={16} className='mr-1' />
                {tList('trigger')}
              </Button>
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
                  <Button size='sm' onClick={() => setCreateOpen(true)}>
                    <Plus size={16} className='mr-1' />
                    {tList('trigger')}
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <DataTable table={table} total={data.length} />
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
