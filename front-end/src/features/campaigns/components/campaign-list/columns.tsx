import { formatDistanceToNow } from 'date-fns';
import { vi } from 'date-fns/locale';
import { Badge } from '@/components/ui/badge';
import type { ColumnDef } from '@tanstack/react-table';
import type { CampaignOut, CampaignStatus } from '../../types';
import { CampaignDevicesSummary } from './CampaignDevicesSummary';
import { CampaignRowActions } from './CampaignRowActions';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { useQuery } from '@tanstack/react-query';
import { executionsApi } from '../../services/api';
import { CampaignRunStats } from './CampaignRunStats';

type TFn = (key: string, values?: Record<string, any>) => string;

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
  statusLabel: Record<CampaignStatus, string>,
  statusVariant: Record<
    CampaignStatus,
    'secondary' | 'default' | 'outline' | 'destructive'
  >
): ColumnDef<CampaignOut>[] {
  const CELL = 'align-middle py-2';
  return [
    {
      id: 'name',
      accessorKey: 'name',
      header: t('colName'),
      size: 320,
      meta: { cellClassName: CELL },
      cell: ({ row }) => {
        const c = row.original;
        return (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className='block max-w-[300px] truncate text-sm font-semibold'>
                {c.name}
              </span>
            </TooltipTrigger>
            <TooltipContent>{c.name}</TooltipContent>
          </Tooltip>
        );
      }
    },
    {
      id: 'descriptionShort',
      header: t('colDescriptionShort'),
      size: 280,
      meta: { cellClassName: CELL },
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
      size: 110,
      meta: { cellClassName: CELL },
      cell: ({ row }) => {
        const c = row.original;
        return (
          <Badge
            variant={statusVariant[c.status]}
            className='inline-flex items-center gap-1 text-[11px]'
          >
            {statusLabel[c.status]}
          </Badge>
        );
      }
    },
    {
      id: 'lastRun',
      header: t('colLastRun'),
      size: 140,
      meta: { cellClassName: CELL },
      cell: ({ row }) => <CampaignLastRunCell campaignId={row.original.id} />
    },
    {
      id: 'runStats',
      header: t('colRunStats'),
      size: 120,
      meta: { cellClassName: CELL },
      cell: ({ row }) => <CampaignRunStats campaignId={row.original.id} />
    },
    {
      id: 'createdAt',
      header: t('colTime'),
      size: 130,
      meta: { cellClassName: CELL },
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
      id: 'devices',
      header: t('colDevices'),
      size: 160,
      meta: { cellClassName: CELL },
      cell: ({ row }) => {
        const c = row.original;
        return (
          <CampaignDevicesSummary
            campaignId={c.id}
            campaignName={c.name}
            targetGroupId={c.target_group_id}
          />
        );
      }
    },
    {
      id: 'actions',
      header: '',
      size: 220,
      meta: {
        cellClassName: `${CELL} whitespace-nowrap`
      },
      cell: ({ row }) => {
        const c = row.original;
        return <CampaignRowActions campaign={c} />;
      }
    }
  ];
}
