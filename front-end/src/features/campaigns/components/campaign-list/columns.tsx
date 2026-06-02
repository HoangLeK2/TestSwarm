import { formatDistanceToNow } from 'date-fns';
import { vi } from 'date-fns/locale';
import { Badge } from '@/components/ui/badge';
import type { ColumnDef } from '@tanstack/react-table';
import type { CampaignOut } from '../../types';
import { campaignStatusLabel, campaignStatusVariant } from '../../campaign-status-ui';
import { CampaignSetupCell } from './CampaignSetupCell';
import { CampaignRowActions } from './CampaignRowActions';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { useQuery } from '@tanstack/react-query';
import { executionsApi } from '../../services/api';
import { CampaignRunStats } from './CampaignRunStats';
import { CampaignEngineBadge } from './CampaignEngineBadge';
import { cn } from '@/lib/utils';

type TFn = (key: string, values?: Record<string, any>) => string;

function responsiveCol(
  cellClassName: string,
  visibility?: 'lg' | 'xl'
) {
  const hide =
    visibility === 'lg'
      ? 'hidden lg:table-cell'
      : visibility === 'xl'
        ? 'hidden xl:table-cell'
        : undefined;
  return {
    cellClassName: cn(cellClassName, hide),
    headerClassName: hide
  };
}

function CampaignLastRunCell({ campaignId }: { campaignId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['campaign-latest-execution', campaignId],
    queryFn: () => executionsApi.list({ campaignId, limit: 1, offset: 0 }),
    staleTime: 10_000,
    refetchInterval: 15_000
  });

  const ex = data?.items?.[0];
  if (!ex && !isLoading)
    return <span className='text-[11px] text-muted-foreground'>—</span>;
  if (!ex) return <span className='text-[11px] text-muted-foreground'>…</span>;

  const ts = ex.finished_at ?? ex.started_at ?? ex.created_at;
  if (!ts) return <span className='text-[11px] text-muted-foreground'>—</span>;

  const date = new Date(ts);
  const exact = Number.isNaN(date.getTime())
    ? String(ts)
    : date.toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' });
  const rel = Number.isNaN(date.getTime())
    ? String(ts)
    : formatDistanceToNow(date, { addSuffix: true, locale: vi });

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className='whitespace-nowrap text-[11px] text-muted-foreground'>
          {rel}
        </span>
      </TooltipTrigger>
      <TooltipContent>{exact}</TooltipContent>
    </Tooltip>
  );
}

export function getCampaignColumns(
  t: TFn,
  statusLabel: Record<string, string>
): ColumnDef<CampaignOut>[] {
  const CELL = 'align-middle py-2';
  return [
    {
      id: 'name',
      accessorKey: 'name',
      header: t('colName'),
      size: 240,
      meta: { cellClassName: CELL },
      cell: ({ row }) => {
        const c = row.original;
        return (
          <div className='min-w-0'>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className='block max-w-[12rem] truncate text-sm font-semibold xl:max-w-[16rem]'>
                  {c.name}
                </span>
              </TooltipTrigger>
              <TooltipContent>{c.name}</TooltipContent>
            </Tooltip>
            <Badge
              variant={campaignStatusVariant(c.status)}
              className='mt-1 inline-flex text-[10px] xl:hidden'
            >
              {campaignStatusLabel(c.status, statusLabel)}
            </Badge>
          </div>
        );
      }
    },
    {
      id: 'descriptionShort',
      header: t('colDescriptionShort'),
      size: 280,
      meta: responsiveCol(CELL, 'xl'),
      cell: ({ row }) => {
        const c = row.original;
        const value = (c.description ?? '').trim();
        if (!value)
          return <span className='text-[11px] text-muted-foreground'>—</span>;
        return (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className='block max-w-[260px] truncate text-[11px] text-muted-foreground'>
                {value}
              </span>
            </TooltipTrigger>
            <TooltipContent className='max-w-[520px] whitespace-pre-wrap'>
              {value}
            </TooltipContent>
          </Tooltip>
        );
      }
    },
    {
      id: 'status',
      header: t('colStatus'),
      size: 96,
      meta: responsiveCol(CELL, 'xl'),
      cell: ({ row }) => {
        const c = row.original;
        return (
          <div className='flex flex-col items-start gap-1'>
            <Badge
              variant={campaignStatusVariant(c.status)}
              className='inline-flex items-center gap-1 text-[11px]'
            >
              {campaignStatusLabel(c.status, statusLabel)}
            </Badge>
            <CampaignEngineBadge campaignId={c.id} status={c.status} />
          </div>
        );
      }
    },
    {
      id: 'lastRun',
      header: t('colLastRun'),
      size: 140,
      meta: responsiveCol(CELL, 'xl'),
      cell: ({ row }) => <CampaignLastRunCell campaignId={row.original.id} />
    },
    {
      id: 'runStats',
      header: t('colRunStats'),
      size: 120,
      meta: responsiveCol(CELL, 'xl'),
      cell: ({ row }) => <CampaignRunStats campaignId={row.original.id} />
    },
    {
      id: 'createdAt',
      header: t('colTime'),
      size: 130,
      meta: responsiveCol(CELL, 'xl'),
      cell: ({ row }) => {
        const c = row.original;
        return (
          <span className='whitespace-nowrap text-[11px] text-muted-foreground'>
            {formatDistanceToNow(new Date(c.created_at), {
              addSuffix: true,
              locale: vi
            })}
          </span>
        );
      }
    },
    {
      id: 'setup',
      header: t('colSetup'),
      size: 176,
      meta: { cellClassName: cn(CELL, 'whitespace-normal') },
      cell: ({ row }) => <CampaignSetupCell campaign={row.original} />
    },
    {
      id: 'actions',
      header: t('colActions'),
      size: 168,
      enablePinning: false,
      meta: {
        cellClassName: cn(CELL, 'w-[1%] whitespace-nowrap'),
        headerClassName: 'w-[1%] whitespace-nowrap'
      },
      cell: ({ row }) => {
        const c = row.original;
        return <CampaignRowActions campaign={c} />;
      }
    }
  ];
}
