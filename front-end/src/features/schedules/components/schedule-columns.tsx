import { formatDistanceToNow } from 'date-fns';
import { vi } from 'date-fns/locale';
import type { ColumnDef } from '@tanstack/react-table';
import { Badge } from '@/components/ui/badge';
import type { ScheduleOut } from '../services/api';
import { cronExpressionToHumanReadable } from './cron-builder';
import { ScheduleRowActions } from './schedule-row-actions';

type TFn = (key: string, values?: Record<string, any>) => string;

export function getScheduleColumns(t: TFn): ColumnDef<ScheduleOut>[] {
  return [
    {
      id: 'name',
      accessorKey: 'name',
      header: t('colName'),
      cell: ({ row }) => (
        <span className='truncate text-sm font-semibold'>{row.original.name}</span>
      )
    },
    {
      id: 'target',
      accessorKey: 'target_type',
      header: t('colTarget'),
      cell: ({ row }) => {
        const s = row.original;
        return (
          <div className='space-y-0.5'>
            <div className='truncate text-sm'>
              <span className='font-medium'>{s.target_type}</span>
            </div>
            <div className='truncate text-[11px] text-muted-foreground'>{s.target_id ?? '-'}</div>
          </div>
        );
      }
    },
    {
      id: 'cron',
      accessorKey: 'cron_expression',
      header: t('colCron'),
      cell: ({ row }) => {
        const s = row.original;
        return (
          <div className='space-y-0.5'>
            <div className='truncate text-sm'>{cronExpressionToHumanReadable(s.cron_expression)}</div>
            <div className='truncate text-[11px] text-muted-foreground font-mono'>{s.cron_expression}</div>
          </div>
        );
      }
    },
    {
      id: 'enabled',
      accessorKey: 'is_enabled',
      header: t('colEnabled'),
      cell: ({ row }) => {
        const isEnabled = row.original.is_enabled;
        return (
          <Badge variant={isEnabled ? 'default' : 'secondary'} className='text-[11px]'>
            {isEnabled ? 'ON' : 'OFF'}
          </Badge>
        );
      }
    },
    {
      id: 'nextRun',
      accessorKey: 'next_run_at',
      header: t('colNextRun'),
      cell: ({ row }) => {
        const v = row.original.next_run_at;
        if (!v) return <span className='text-[11px] text-muted-foreground'>-</span>;
        return (
          <span className='whitespace-nowrap text-[11px] text-muted-foreground'>
            {formatDistanceToNow(new Date(v), { addSuffix: true, locale: vi })}
          </span>
        );
      }
    },
    {
      id: 'runs',
      accessorKey: 'run_count',
      header: t('colRuns'),
      cell: ({ row }) => (
        <Badge variant='secondary' className='text-[11px]'>
          {row.original.run_count}
        </Badge>
      )
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => <ScheduleRowActions schedule={row.original} />
    }
  ];
}

