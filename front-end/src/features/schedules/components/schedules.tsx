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

export function Schedules() {
  const t = useTranslations('schedulesFeature.list');
  const { data: schedules, isLoading, error } = useSchedules();

  const data: ScheduleOut[] = schedules ?? [];
  const columns = useMemo(() => getScheduleColumns(t), [t]);

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
          {isLoading && <p className='text-sm text-muted-foreground'>{t('loading')}</p>}
          {error && <p className='text-sm text-destructive'>{t('loadError')}</p>}
        </div>
      ) : (
        <>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <p className='text-muted-foreground'>
              <span className='font-medium text-foreground'>{schedules?.length ?? 0}</span> {t('countLabel')}
            </p>
            <Button size='sm' onClick={() => setCreateOpen(true)}>
              <Plus size={16} className='mr-1' />
              {t('trigger')}
            </Button>
          </div>

          {!schedules?.length ? (
            <div className='rounded-xl border border-dashed border-border bg-muted/20 p-16 text-center'>
              <FileText className='mx-auto mb-4 size-12 text-muted-foreground/80' />
              <p className='text-sm font-medium text-foreground'>{t('emptyTitle')}</p>
              <p className='mt-1 text-sm text-muted-foreground'>{t('emptyDescription')}</p>
              <div className='mt-6'>
                <Button size='sm' onClick={() => setCreateOpen(true)}>
                  <Plus size={16} className='mr-1' />
                  {t('trigger')}
                </Button>
              </div>
            </div>
          ) : (
            <DataTable table={table} total={data.length} />
          )}

          {createOpen && (
            <ScheduleFormDialog open={createOpen} onOpenChange={setCreateOpen} mode='create' />
          )}
        </>
      )}
    </div>
  );
}

