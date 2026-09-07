'use client';

import { formatDistanceToNow } from 'date-fns';
import { vi } from 'date-fns/locale';
import type { Locale } from 'date-fns';
import Link from 'next/link';
import { MoreHorizontal } from 'lucide-react';
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
import { useOrganization } from '@/features/organization/hooks/use-organization';
import { TagsCell } from './TagsCell';
import { DeviceCmdButton } from './BootstrapDialog';
import type { ConfirmModalOptions } from '@/providers/modal-provider';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { ROUTES } from '@/config/routes';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';

const DEVICE_COMMAND_LABEL_KEY = {
  bootstrap: 'setup',
  restart_u2: 'restartControl'
} as const;

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
  const { currentOrg } = useOrganization();
  const perms = useResourcePermissions('devices');
  const canReviveDead = perms.canManage;

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
      removeDeviceFromCache(qc, device.id, currentOrg?.id);
    } finally {
      setDeletingId((prev) => (prev === device.id ? null : prev));
    }
  };

  const hasRelay = !!resolveDeviceRelay(device, relayMap);
  const fsm = deviceFsmStateOf(device);

  return (
    <div className='flex min-w-max items-center justify-end gap-1.5'>
      {canReviveDead && fsm === 'dead' && (
        <ReviveDeviceButton device={device} />
      )}
      {perms.canExecute && hasRelay && fsm !== 'dead' && (
        <span className='sr-only'>{t('commandsAvailable')}</span>
      )}
      {perms.canExecute ? (
        <Button
          size='sm'
          variant='outline'
          onClick={() => setConnectDevice(device)}
          className='h-8'
        >
          {t('connect')}
        </Button>
      ) : null}
      {(perms.canDelete ||
        (perms.canExecute && hasRelay && fsm !== 'dead')) && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant='ghost'
              size='icon'
              className='size-8'
              aria-label={t('actions')}
            >
              <MoreHorizontal size={16} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align='end' className='w-56'>
            {perms.canExecute && hasRelay && fsm !== 'dead' ? (
              <>
                {(['bootstrap', 'restart_u2'] as const).map((cmd) => (
                  <DeviceCmdButton
                    key={cmd}
                    device={device}
                    cmd={cmd}
                    trigger={
                      <DropdownMenuItem
                        onSelect={(event) => event.preventDefault()}
                      >
                        {t(`commands.${DEVICE_COMMAND_LABEL_KEY[cmd]}.label`)}
                      </DropdownMenuItem>
                    }
                  />
                ))}
              </>
            ) : null}
            {perms.canDelete &&
            perms.canExecute &&
            hasRelay &&
            fsm !== 'dead' ? (
              <DropdownMenuSeparator />
            ) : null}
            {perms.canDelete ? (
              <DropdownMenuItem
                variant='destructive'
                disabled={deletingId === device.id}
                onSelect={() => void handleDelete()}
              >
                {deletingId === device.id ? t('deleting') : t('deleteDevice')}
              </DropdownMenuItem>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
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
            <Link
              href={ROUTES.DEVICES.DETAIL(d.serial)}
              className='truncate text-sm font-medium hover:underline'
            >
              {label}
            </Link>
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
            <span className='inline-flex items-center gap-1.5 text-[10px] text-muted-foreground'>
              <span
                className={`size-1.5 rounded-full ${transportOnline ? 'bg-emerald-500' : 'bg-muted-foreground/50'}`}
              />
              {transportOnline ? t('transportOnline') : t('transportOffline')}
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
              {relay.name || relay.relay_id}
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
