import { formatDistanceToNow } from 'date-fns';
import { vi } from 'date-fns/locale';
import { Badge } from '@/components/ui/badge';
import type { ColumnDef } from '@tanstack/react-table';
import type { CampaignOut, CampaignStatus } from '../../types';
import { CampaignDevicesSummary } from './CampaignDevicesSummary';
import { CampaignRowActions } from './CampaignRowActions';

type TFn = (key: string, values?: Record<string, any>) => string;

export function getCampaignColumns(
  t: TFn,
  statusLabel: Record<CampaignStatus, string>,
  statusVariant: Record<CampaignStatus, 'secondary' | 'default' | 'outline' | 'destructive'>
): ColumnDef<CampaignOut>[] {
  return [
    {
      id: 'name',
      accessorKey: 'name',
      header: t('colName'),
      cell: ({ row }) => {
        const c = row.original;
        return <span className='truncate text-sm font-semibold'>{c.name}</span>;
      }
    },
    {
      id: 'status',
      header: t('colStatus'),
      cell: ({ row }) => {
        const c = row.original;
        return (
          <Badge variant={statusVariant[c.status]} className='inline-flex items-center gap-1 text-[11px]'>
            {statusLabel[c.status]}
          </Badge>
        );
      }
    },
    {
      id: 'createdAt',
      header: t('colTime'),
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
      cell: ({ row }) => {
        const c = row.original;
        return <CampaignDevicesSummary campaignId={c.id} />;
      }
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => {
        const c = row.original;
        return <CampaignRowActions campaign={c} />;
      }
    }
  ];
}

