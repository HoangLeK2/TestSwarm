import { formatDistanceToNow } from 'date-fns';
import { vi } from 'date-fns/locale';
import { QrCode, Trash2, Wifi, WifiOff } from 'lucide-react';
import type { ColumnDef } from '@tanstack/react-table';
import { Badge } from '../../../../components/ui/badge';
import { Button } from '../../../../components/ui/button';
import {
  devicesApi,
  isPendingDevice,
  type DeviceOut,
  type RelayAgentOut
} from '../../services/manage-api';
import {
  isDeviceOnlineForList,
  resolveDeviceRelay
} from '../../lib/device-online';
import { TagsCell } from './TagsCell';
import { DeviceCmdButton } from './BootstrapDialog';
import type { ConfirmModalOptions } from '@/providers/modal-provider';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';

function DeviceActionsCell({
  device,
  relayMap,
  deletingId,
  setDeletingId,
  setConnectDevice,
  confirm,
  t,
  tCommon
}: {
  device: DeviceOut;
  relayMap: Record<string, RelayAgentOut>;
  deletingId: string | null;
  setDeletingId: (
    id: string | null | ((prev: string | null) => string | null)
  ) => void;
  setConnectDevice: (device: DeviceOut | null) => void;
  confirm: (options: ConfirmModalOptions) => Promise<boolean>;
  t: (key: string, values?: Record<string, any>) => string;
  tCommon: (key: string, values?: Record<string, any>) => string;
}) {
  const handleDelete = async () => {
    const ok = await confirm({
      title: t('deleteDevice'),
      description: t('deleteConfirm'),
      confirmText: tCommon('confirm'),
      cancelText: tCommon('cancel'),
      confirmVariant: 'destructive',
      zIndex: 10_000
    });
    setDeletingId(device.id);
    try {
      await devicesApi.delete(device.id);
      window.location.reload();
    } finally {
      setDeletingId((prev) => (prev === device.id ? null : prev));
    }
  };

  const hasRelay = !!resolveDeviceRelay(device, relayMap);

  return (
    <div className='flex items-center justify-end gap-1'>
      {hasRelay && (
        <>
          <DeviceCmdButton device={device} cmd='bootstrap' />
          <DeviceCmdButton device={device} cmd='restart_u2' />
          <DeviceCmdButton device={device} cmd='restart_scrcpy' />
        </>
      )}
      <Button
        size='sm'
        variant='outline'
        onClick={() => setConnectDevice(device)}
      >
        <QrCode size={14} className='mr-1.5' />
        {t('connect')}
      </Button>
      <Tooltip delayDuration={400}>
        <TooltipTrigger asChild>
          <Button
            size='icon'
            variant='ghost'
            className='size-7 text-destructive hover:text-destructive'
            disabled={deletingId === device.id}
            onClick={handleDelete}
            aria-label={t('deleteDevice')}
          >
            <Trash2 size={14} />
          </Button>
        </TooltipTrigger>
        <TooltipContent side='bottom'>{t('deleteDevice')}</TooltipContent>
      </Tooltip>
    </div>
  );
}

export function getDeviceColumns({
  t,
  tCommon,
  deletingId,
  setDeletingId,
  setConnectDevice,
  relayMap = {},
  confirm
}: {
  t: (key: string, values?: Record<string, any>) => string;
  tCommon: (key: string, values?: Record<string, any>) => string;
  deletingId: string | null;
  setDeletingId: (
    id: string | null | ((prev: string | null) => string | null)
  ) => void;
  setConnectDevice: (device: DeviceOut | null) => void;
  relayMap?: Record<string, RelayAgentOut>;
  confirm: (options: ConfirmModalOptions) => Promise<boolean>;
}): ColumnDef<DeviceOut>[] {
  return [
    {
      id: 'name',
      accessorKey: 'name',
      header: t('columns.device'),
      cell: ({ row }) => {
        const d = row.original;
        const pending = isPendingDevice(d);
        const label = pending
          ? d.name || t('newDevice')
          : d.name || `${d.brand} ${d.model}`.trim() || d.serial;

        return (
          <div className='flex flex-col'>
            <span className='truncate text-sm font-medium'>{label}</span>
            <span className='font-mono text-[11px] text-muted-foreground'>
              {pending ? t('notConnected') : d.serial}
            </span>
          </div>
        );
      }
    },
    {
      id: 'status',
      header: t('columns.status'),
      cell: ({ row }) => {
        const d = row.original;
        const pending = isPendingDevice(d);
        const isOnline = isDeviceOnlineForList(d, relayMap);

        return (
          <Badge
            variant={pending ? 'outline' : isOnline ? 'secondary' : 'outline'}
            className='inline-flex items-center gap-1 text-[11px]'
          >
            {pending ? (
              t('notConnected')
            ) : isOnline ? (
              <>
                <Wifi size={10} />
                {t('online')}
              </>
            ) : (
              <>
                <WifiOff size={10} />
                {t('offline')}
              </>
            )}
          </Badge>
        );
      }
    },
    {
      id: 'specs',
      header: t('columns.specs'),
      cell: ({ row }) => {
        const d = row.original;
        return (
          <div className='space-y-0.5 text-[11px] text-muted-foreground'>
            {d.brand && (
              <div>
                <span className='font-medium'>{t('labels.model')}:</span>{' '}
                {d.brand} {d.model}
              </div>
            )}
            {d.android_version && (
              <div>
                <span className='font-medium'>{t('labels.android')}:</span>{' '}
                {d.android_version} (SDK {d.sdk_version})
              </div>
            )}
            {d.adb_serial && (
              <div>
                <span className='font-medium'>{t('labels.adbSerial')}:</span>{' '}
                <span className='font-mono'>{d.adb_serial}</span>
              </div>
            )}
            {d.screen_width > 0 && (
              <div>
                <span className='font-medium'>{t('labels.screen')}:</span>{' '}
                {d.screen_width}×{d.screen_height}
              </div>
            )}
          </div>
        );
      }
    },
    {
      id: 'tags',
      header: t('columns.tags'),
      cell: ({ row }) => {
        const d = row.original;
        return <TagsCell deviceId={d.id} tags={d.tags} />;
      }
    },
    {
      id: 'lastSeen',
      header: t('columns.lastSeen'),
      cell: ({ row }) => {
        const d = row.original;
        if (!d.last_seen)
          return <span className='text-[11px] text-muted-foreground'>—</span>;

        return (
          <span className='text-[11px] text-muted-foreground'>
            {formatDistanceToNow(new Date(d.last_seen), {
              addSuffix: true,
              locale: vi
            })}
          </span>
        );
      }
    },
    {
      id: 'relay',
      header: t('columns.connectionHost'),
      cell: ({ row }) => {
        const d = row.original;
        const relay = resolveDeviceRelay(d, relayMap);
        if (!relay)
          return <span className='text-[11px] text-muted-foreground'>—</span>;
        return (
          <div className='flex items-center gap-1'>
            <span
              className={`size-1.5 rounded-full ${relay.status === 'online' ? 'bg-green-500' : 'bg-gray-400'}`}
            />
            <span className='font-mono text-[11px]'>
              {relay.hostname || relay.relay_id}
            </span>
          </div>
        );
      }
    },
    {
      id: 'actions',
      header: '',
      meta: { cellClassName: 'relative z-20 bg-background' },
      cell: ({ row }) => (
        <DeviceActionsCell
          device={row.original}
          relayMap={relayMap}
          deletingId={deletingId}
          setDeletingId={setDeletingId}
          setConnectDevice={setConnectDevice}
          confirm={confirm}
          t={t}
          tCommon={tCommon}
        />
      )
    }
  ];
}
