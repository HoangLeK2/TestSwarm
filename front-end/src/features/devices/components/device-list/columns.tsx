import { formatDistanceToNow } from 'date-fns';
import { vi } from 'date-fns/locale';
import { QrCode, Trash2, Wifi, WifiOff } from 'lucide-react';
import type { ColumnDef } from '@tanstack/react-table';
import { Badge } from '../../../../components/ui/badge';
import { Button } from '../../../../components/ui/button';
import { devicesApi, isPendingDevice, type DeviceOut, type RelayAgentOut } from '../../services/manage-api';
import { TagsCell } from './TagsCell';
import { DeviceCmdButton } from './BootstrapDialog';

function DeviceActionsCell({
  device,
  relayMap,
  deletingId,
  setDeletingId,
  setConnectDevice,
  t,
}: {
  device: DeviceOut;
  relayMap: Record<string, RelayAgentOut>;
  deletingId: string | null;
  setDeletingId: (id: string | null | ((prev: string | null) => string | null)) => void;
  setConnectDevice: (device: DeviceOut | null) => void;
  t: (key: string, values?: Record<string, any>) => string;
}) {
  const handleDelete = async () => {
    if (!window.confirm(t('deleteConfirm'))) return;
    setDeletingId(device.id);
    try {
      await devicesApi.delete(device.id);
      window.location.reload();
    } finally {
      setDeletingId((prev) => (prev === device.id ? null : prev));
    }
  };

  const hasRelay = !!(
    (device.relay_id ? relayMap[device.relay_id] : undefined) ??
    relayMap[device.serial] ??
    (device.adb_ip ? relayMap[device.adb_ip] : undefined)
  );

  return (
    <div className='flex items-center justify-end gap-1'>
      {hasRelay && (
        <>
          <DeviceCmdButton device={device} cmd='bootstrap' />
          <DeviceCmdButton device={device} cmd='restart_u2' />
          <DeviceCmdButton device={device} cmd='restart_scrcpy' />
        </>
      )}
      <Button size='sm' variant='outline' onClick={() => setConnectDevice(device)}>
        <QrCode size={14} className='mr-1.5' />
        {t('connect')}
      </Button>
      <Button
        size='icon'
        variant='ghost'
        className='size-7 text-destructive hover:text-destructive'
        disabled={deletingId === device.id}
        onClick={handleDelete}
        title={t('deleteDevice')}
      >
        <Trash2 size={14} />
      </Button>
    </div>
  );
}

export function getDeviceColumns({
  t,
  deletingId,
  setDeletingId,
  setConnectDevice,
  relayMap = {}
}: {
  t: (key: string, values?: Record<string, any>) => string;
  deletingId: string | null;
  setDeletingId: (id: string | null | ((prev: string | null) => string | null)) => void;
  setConnectDevice: (device: DeviceOut | null) => void;
  relayMap?: Record<string, RelayAgentOut>;
}): ColumnDef<DeviceOut>[] {
  return [
    {
      id: 'name',
      accessorKey: 'name',
      header: t('columns.device'),
      cell: ({ row }) => {
        const d = row.original;
        const pending = isPendingDevice(d);
        const label = pending ? d.name || t('newDevice') : d.name || `${d.brand} ${d.model}`.trim() || d.serial;

        return (
          <div className='flex flex-col'>
            <span className='truncate text-sm font-medium'>{label}</span>
            <span className='font-mono text-[11px] text-muted-foreground'>{pending ? t('notConnected') : d.serial}</span>
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
        const isOnline = d.last_seen ? Date.now() - new Date(d.last_seen).getTime() < 60_000 : false;

        return (
          <Badge variant={pending ? 'outline' : isOnline ? 'secondary' : 'outline'} className='inline-flex items-center gap-1 text-[11px]'>
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
                <span className='font-medium'>{t('labels.model')}:</span> {d.brand} {d.model}
              </div>
            )}
            {d.android_version && (
              <div>
                <span className='font-medium'>{t('labels.android')}:</span> {d.android_version} (SDK {d.sdk_version})
              </div>
            )}
            {d.screen_width > 0 && (
              <div>
                <span className='font-medium'>{t('labels.screen')}:</span> {d.screen_width}×{d.screen_height}
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
        if (!d.last_seen) return <span className='text-[11px] text-muted-foreground'>—</span>;

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
      header: 'Relay',
      cell: ({ row }) => {
        const d = row.original;
        const relay =
          (d.relay_id ? relayMap[d.relay_id] : undefined) ??
          relayMap[d.serial] ??
          (d.adb_ip ? relayMap[d.adb_ip] : undefined);
        if (!relay) return <span className='text-[11px] text-muted-foreground'>—</span>;
        return (
          <div className='flex items-center gap-1'>
            <span className={`size-1.5 rounded-full ${relay.status === 'online' ? 'bg-green-500' : 'bg-gray-400'}`} />
            <span className='font-mono text-[11px]'>{relay.hostname || relay.relay_id}</span>
          </div>
        );
      }
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <DeviceActionsCell
          device={row.original}
          relayMap={relayMap}
          deletingId={deletingId}
          setDeletingId={setDeletingId}
          setConnectDevice={setConnectDevice}
          t={t}
        />
      )
    }
  ];
}

