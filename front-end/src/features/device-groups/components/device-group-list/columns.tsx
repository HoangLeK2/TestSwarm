'use client';

import { formatDistanceToNow } from 'date-fns';
import { enUS, vi } from 'date-fns/locale';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Trash2 } from 'lucide-react';
import type { ColumnDef } from '@tanstack/react-table';
import type { DeviceGroupOut } from '../../services/api';
import { AddDevicesToGroupDialog } from '../add-devices-to-group-dialog';
import { EditDeviceGroupDialog } from '../edit-device-group-dialog';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';

type TFn = (key: string, values?: Record<string, any>) => string;

function DeviceGroupActionsCell({
  group,
  onDelete,
  t
}: {
  group: DeviceGroupOut;
  onDelete: (group: DeviceGroupOut) => void;
  t: TFn;
}) {
  const perms = useResourcePermissions('device-groups');

  return (
    <div className='flex items-center gap-1'>
      {perms.canUpdate ? <AddDevicesToGroupDialog groupId={group.id} /> : null}
      {perms.canUpdate ? <EditDeviceGroupDialog group={group} /> : null}
      {perms.canDelete ? (
        <Button
          size='icon'
          variant='ghost'
          className='size-8 text-destructive hover:text-destructive'
          onClick={() => onDelete(group)}
          aria-label={t('deleteAction', { name: group.name })}
        >
          <Trash2 size={14} />
        </Button>
      ) : null}
    </div>
  );
}

export function getDeviceGroupColumns(
  t: TFn,
  onDelete: (group: DeviceGroupOut) => void,
  onSelect: (group: DeviceGroupOut) => void,
  locale: string
): ColumnDef<DeviceGroupOut>[] {
  const dateLocale = locale === 'vi' ? vi : enUS;

  return [
    {
      id: 'color',
      header: '',
      cell: ({ row }) => (
        <div
          className='size-4 rounded-full'
          style={{ backgroundColor: row.original.color }}
          role='img'
          aria-label={t('colorDotLabel', { name: row.original.name })}
        />
      ),
      size: 40
    },
    {
      id: 'name',
      accessorKey: 'name',
      header: t('colName'),
      cell: ({ row }) => (
        <button
          className='truncate text-sm font-semibold hover:underline'
          onClick={() => onSelect(row.original)}
        >
          {row.original.name}
        </button>
      )
    },
    {
      id: 'description',
      accessorKey: 'description',
      header: t('colDescription'),
      cell: ({ row }) => (
        <span className='truncate text-sm text-muted-foreground'>
          {row.original.description || '-'}
        </span>
      )
    },
    {
      id: 'deviceCount',
      header: t('colDeviceCount'),
      cell: ({ row }) => (
        <Badge variant='secondary'>{row.original.device_count}</Badge>
      )
    },
    {
      id: 'createdAt',
      header: t('colTime'),
      cell: ({ row }) => (
        <span className='whitespace-nowrap text-[11px] text-muted-foreground'>
          {formatDistanceToNow(new Date(row.original.created_at), {
            addSuffix: true,
            locale: dateLocale
          })}
        </span>
      )
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <DeviceGroupActionsCell
          group={row.original}
          onDelete={onDelete}
          t={t}
        />
      )
    }
  ];
}
