'use client';

import { formatDistanceToNow } from 'date-fns';
import { enUS, vi } from 'date-fns/locale';
import type { Locale } from 'date-fns';
import { QrCode, Trash2, Wifi, WifiOff } from 'lucide-react';
import type { ColumnDef } from '@tanstack/react-table';
import { useQueryClient } from '@tanstack/react-query';
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
import {
  DEVICE_FSM_BADGE_CLASS,
  DEVICE_FSM_BADGE_VARIANT,
  deviceFsmStateOf,
  type DeviceFsmStateKey
} from '../../lib/device-fsm';
import { ReviveDeviceButton } from './ReviveDeviceButton';
import { removeDeviceFromCache } from '../../hooks/use-devices';
import { TagsCell } from './TagsCell';
import { DeviceCmdButton } from './BootstrapDialog';
import type { ConfirmModalOptions } from '@/providers/modal-provider';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { normalizeNavUserRole } from '@/lib/nav-access';
import { useAuthContext } from '@/features/auth/providers/auth-provider';

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
  const qc = useQueryClient();
  const perms = useResourcePermissions('devices');
  const { user } = useAuthContext();
  const platformRole = normalizeNavUserRole(user?.role);
  const canReviveDead =
    platformRole === 'admin' || platformRole === 'superadmin';

  const handleDelete = async () => {
    const ok = await confirm({
      title: t('deleteDevice'),
      description: t('deleteConfirm'),
      confirmText: tCommon('confirm'),
      cancelText: tCommon('cancel'),
      confirmVariant: 'destructive',
      zIndex: 10_000
    });
    if (!ok) return;

    setDeletingId(device.id);
    try {
      await devicesApi.delete(device.id);
      removeDeviceFromCache(qc, device.id);
    } finally {
      setDeletingId((prev) => (prev === device.id ? null : prev));
    }
  };

  const hasRelay = !!resolveDeviceRelay(device, relayMap);
  const fsm = deviceFsmStateOf(device);

  return (
    <div className='flex items-center justify-end gap-1'>
      {canReviveDead && fsm === 'dead' && (
        <ReviveDeviceButton device={device} />
      )}
      {perms.canExecute && hasRelay && fsm !== 'dead' && (
        <>
          <DeviceCmdButton device={device} cmd='bootstrap' />
          <DeviceCmdButton device={device} cmd='restart_u2' />
          <DeviceCmdButton device={device} cmd='restart_scrcpy' />
        </>
      )}
      {perms.canExecute ? (
        <Button
          size='sm'
          variant='outline'
          onClick={() => setConnectDevice(device)}
        >
          <QrCode size={14} className='mr-1.5' />
          {t('connect')}
        </Button>
      ) : null}
      {perms.canDelete ? (
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
      ) : null}
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
  confirm,
  dateLocale = vi
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
  dateLocale?: Locale;
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
        if (pending) {
          return (
            <Badge variant='outline' className='text-[11px]'>
              {t('notConnected')}
            </Badge>
          );
        }

        const fsm = deviceFsmStateOf(d);
        const transportOnline = isDeviceOnlineForList(d, relayMap);
        const variant = DEVICE_FSM_BADGE_VARIANT[fsm];
        const extraClass = DEVICE_FSM_BADGE_CLASS[fsm] ?? '';

        return (
          <div className='flex flex-col gap-1'>
            <Badge
              variant={variant}
              className={`inline-flex w-fit items-center gap-1 text-[11px] ${extraClass}`}
            >
              {t(`fsm.${fsm}` as `fsm.${DeviceFsmStateKey}`)}
            </Badge>
            <span className='inline-flex items-center gap-1 text-[10px] text-muted-foreground'>
              {transportOnline ? (
                <>
                  <Wifi size={10} className='text-green-600' />
                  {t('transportOnline')}
                </>
              ) : (
                <>
                  <WifiOff size={10} />
                  {t('transportOffline')}
                </>
              )}
            </span>
          </div>
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
      header: t('columns.lastHeartbeat'),
      cell: ({ row }) => {
        const d = row.original;
        if (!d.last_seen)
          return <span className='text-[11px] text-muted-foreground'>—</span>;

        const at = new Date(d.last_seen);
        const relative = formatDistanceToNow(at, {
          addSuffix: true,
          locale: dateLocale
        });
        const absolute = at.toLocaleString(
          dateLocale === vi ? 'vi-VN' : 'en-US',
          {
            dateStyle: 'short',
            timeStyle: 'medium'
          }
        );

        return (
          <Tooltip delayDuration={300}>
            <TooltipTrigger asChild>
              <span className='cursor-default text-[11px] text-muted-foreground'>
                {relative}
              </span>
            </TooltipTrigger>
            <TooltipContent side='top' className='font-mono text-xs'>
              {absolute}
            </TooltipContent>
          </Tooltip>
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
