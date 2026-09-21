import { formatDistanceToNow } from 'date-fns';
import { vi } from 'date-fns/locale';
import type { ColumnDef } from '@tanstack/react-table';
import { Badge } from '@/components/ui/badge';
import type { ScheduleOut } from '../services/api';
import { cronExpressionToHumanReadable } from './cron-builder';
import { ScheduleRowActions } from './schedule-row-actions';
import {
  isCampaignActiveExecution,
  type CampaignOut
} from '@/features/campaigns/types';

type TFn = (key: string, values?: Record<string, any>) => string;
type TargetLookup = {
  campaignById: Map<string, CampaignOut>;
  templateById: Map<string, { id: string; name: string }>;
  orgScenarioById: Map<string, { id: string; name: string }>;
};

export function getScheduleColumns(
  tList: TFn,
  tCron: TFn,
  lookup: TargetLookup
): ColumnDef<ScheduleOut>[] {
  return [
    {
      id: 'name',
      accessorKey: 'name',
      header: tList('colName'),
      meta: {
        headerClassName: 'w-[15rem]',
        cellClassName: 'py-3 align-middle'
      },
      cell: ({ row }) => (
        <span className='block max-w-[14rem] truncate text-sm font-semibold'>
          {row.original.name}
        </span>
      )
    },
    {
      id: 'target',
      accessorKey: 'target_type',
      header: tList('colTarget'),
      meta: {
        headerClassName: 'w-[15rem]',
        cellClassName: 'py-3 align-middle'
      },
      cell: ({ row }) => {
        const s = row.original;
        const targetCampaign =
          s.target_type === 'campaign' && s.target_id
            ? lookup.campaignById.get(s.target_id)
            : null;
        const targetTemplate =
          s.target_type === 'template' && s.target_id
            ? lookup.templateById.get(s.target_id)
            : null;
        const targetOrgScenario =
          s.target_type === 'org_scenario' && s.target_id
            ? lookup.orgScenarioById.get(s.target_id)
            : null;
        const targetName =
          targetCampaign?.name ??
          targetTemplate?.name ??
          targetOrgScenario?.name;
        const targetDetail =
          targetName ??
          (s.target_id ? `${tList('targetIdPrefix')}: ${s.target_id}` : null);
        const isRunningCampaign = targetCampaign
          ? isCampaignActiveExecution(targetCampaign.status)
          : false;
        const targetLabel =
          s.target_type === 'campaign'
            ? tList('targetCampaign')
            : s.target_type === 'template'
              ? tList('targetTemplate')
              : s.target_type === 'org_scenario'
                ? tList('targetOrgScenario')
                : s.target_type === 'fleet'
                  ? tList('targetFleet')
                  : s.target_type;
        return (
          <div className='min-w-0 space-y-1'>
            <div className='flex min-w-0 items-center gap-2'>
              <span className='truncate text-sm font-medium'>
                {targetLabel}
              </span>
              {isRunningCampaign && (
                <Badge className='shrink-0 bg-emerald-600 text-[10px] text-white hover:bg-emerald-600'>
                  {tList('targetRunning')}
                </Badge>
              )}
            </div>
            {targetDetail && (
              <div
                className='truncate text-xs text-muted-foreground'
                title={targetDetail}
              >
                {targetDetail}
              </div>
            )}
          </div>
        );
      }
    },
    {
      id: 'cron',
      accessorKey: 'cron_expression',
      header: tList('colCron'),
      meta: {
        headerClassName: 'w-[13rem]',
        cellClassName: 'py-3 align-middle'
      },
      cell: ({ row }) => {
        const s = row.original;
        const cronExpression = s.cron_expression ?? '';
        const human = cronExpression
          ? cronExpressionToHumanReadable(cronExpression, tCron)
          : '-';
        const parsed = human !== cronExpression;
        return (
          <div className='space-y-0.5'>
            <div className='truncate text-sm'>{human}</div>
            {cronExpression && !parsed && (
              <div className='truncate font-mono text-[11px] text-muted-foreground'>
                {cronExpression}
              </div>
            )}
          </div>
        );
      }
    },
    {
      id: 'enabled',
      accessorKey: 'is_enabled',
      header: tList('colEnabled'),
      meta: {
        headerClassName: 'w-[7rem]',
        cellClassName: 'py-3 align-middle'
      },
      cell: ({ row }) => {
        const isEnabled = row.original.is_enabled;
        return (
          <Badge
            variant={isEnabled ? 'default' : 'secondary'}
            className='text-[11px]'
          >
            {isEnabled ? tList('enabledOn') : tList('enabledOff')}
          </Badge>
        );
      }
    },
    {
      id: 'nextRun',
      accessorKey: 'next_run_at',
      header: tList('colNextRun'),
      meta: {
        headerClassName: 'w-[12rem]',
        cellClassName: 'py-3 align-middle'
      },
      cell: ({ row }) => {
        const v = row.original.next_run_at;
        if (!v)
          return <span className='text-[11px] text-muted-foreground'>-</span>;
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
      header: tList('colRuns'),
      meta: {
        headerClassName: 'w-[8rem]',
        cellClassName: 'py-3 align-middle'
      },
      cell: ({ row }) => (
        <Badge variant='secondary' className='text-[11px]'>
          {row.original.run_count}
        </Badge>
      )
    },
    {
      id: 'actions',
      header: '',
      meta: {
        headerClassName: 'w-[10rem]',
        cellClassName: 'py-3 align-middle text-right'
      },
      cell: ({ row }) => <ScheduleRowActions schedule={row.original} />
    }
  ];
}
