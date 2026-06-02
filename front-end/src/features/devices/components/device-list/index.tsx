'use client';

import { useMemo, useState } from 'react';
import { Smartphone } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import type { DeviceOut, RelayAgentOut } from '../../services/manage-api';
import { relayAgentsApi } from '../../services/manage-api';
import { useDevices, useFleetStats } from '../../hooks/use-devices';
import { useDeviceListRealtime } from '../../hooks/use-device-list-realtime';
import { useLifecycleWsConnected } from '../../lib/lifecycle-ws-store';
import { RegisterDeviceDialog } from '../register-device-dialog';
import { DataTable } from '@/components/ui/table/data-table';
import { useDataTable } from '@/hooks/use-data-table';
import { isDeviceOnlineForList } from '../../lib/device-online';
import {
  matchesDeviceFsmFilter,
  type DeviceFsmFilterKey
} from '../../lib/device-fsm';
import { getDeviceColumns } from './columns';
import { ConnectDialog } from './ConnectDialog';
import { FleetStatsSummary } from './FleetStatsSummary';
import { useLocale, useTranslations } from 'next-intl';
import { enUS, vi } from 'date-fns/locale';
import { Can } from '@/features/auth';
import { useAuthContext } from '@/features/auth/providers/auth-provider';
import { useConfirm } from '@/providers/modal-provider';
import { CoreEmptyState } from '@/components/core-empty-state';
import { ROUTES } from '@/config/routes';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { ArrowDownWideNarrow, ArrowUpWideNarrow } from 'lucide-react';

const DEFAULT_FILTER: DeviceFsmFilterKey = 'all';

export function DeviceList() {
  const locale = useLocale();
  const dateLocale = locale.startsWith('vi') ? vi : enUS;
  const t = useTranslations('devicesList');
  const tEmpty = useTranslations('coreEmptyState');
  const tCommon = useTranslations('common');
  const confirm = useConfirm();
  const { user } = useAuthContext();
  useDeviceListRealtime();
  const wsLive = useLifecycleWsConnected();

  const { data: devices, isLoading, error } = useDevices();
  const {
    data: fleetStats,
    isLoading: fleetStatsLoading,
    isError: fleetStatsError
  } = useFleetStats();
  const [connectDevice, setConnectDevice] = useState<DeviceOut | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] =
    useState<DeviceFsmFilterKey>(DEFAULT_FILTER);
  const [sortLastSeenDesc, setSortLastSeenDesc] = useState(true);

  const { data: relayAgents } = useQuery<RelayAgentOut[]>({
    queryKey: ['relay-agents'],
    queryFn: relayAgentsApi.list,
    staleTime: 15_000,
    refetchInterval: 30_000
  });

  const relayMap = useMemo(() => {
    const m: Record<string, RelayAgentOut> = {};
    for (const agent of relayAgents ?? []) {
      m[agent.relay_id] = agent;
      for (const serial of agent.serials) {
        m[serial] = agent;
        const colonIdx = serial.lastIndexOf(':');
        if (colonIdx > 0) {
          m[serial.slice(0, colonIdx)] = agent;
        }
      }
    }
    return m;
  }, [relayAgents]);

  const data: DeviceOut[] = useMemo(() => devices ?? [], [devices]);

  const filteredSortedData = useMemo(() => {
    const isOnline = (d: DeviceOut) => isDeviceOnlineForList(d, relayMap);

    const filtered = data.filter((d) =>
      matchesDeviceFsmFilter(d, statusFilter, isOnline)
    );

    const toTs = (d: DeviceOut) =>
      d.last_seen ? new Date(d.last_seen).getTime() : 0;
    const sorted = [...filtered].sort((a, b) => {
      const da = toTs(a);
      const db = toTs(b);
      return sortLastSeenDesc ? db - da : da - db;
    });
    return sorted;
  }, [data, relayMap, sortLastSeenDesc, statusFilter]);

  const registeredSerials = useMemo(() => {
    const serials = new Set<string>();
    for (const device of data) {
      serials.add(device.serial);
      if (device.adb_serial) serials.add(device.adb_serial);
    }
    return serials;
  }, [data]);

  const columns = useMemo(
    () =>
      getDeviceColumns({
        t,
        tCommon,
        deletingId,
        setDeletingId,
        setConnectDevice,
        relayMap,
        confirm,
        dateLocale
      }),
    [deletingId, t, tCommon, relayMap, confirm, dateLocale]
  );

  const { table } = useDataTable<DeviceOut>({
    data: filteredSortedData,
    columns,
    pageCount: 1
  });

  if (error && !devices)
    return <p className='text-sm text-destructive'>{t('loadError')}</p>;

  return (
    <div className='space-y-4'>
      <div className='flex items-center justify-between gap-3'>
        <div className='flex min-w-0 flex-wrap items-center gap-2'>
          <h2 className='text-lg font-semibold'>
            {t('title', { count: devices?.length ?? 0 })}
          </h2>
          {user ? (
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs ${
                wsLive
                  ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                  : 'bg-muted text-muted-foreground'
              }`}
              title={
                wsLive ? t('realtime.connected') : t('realtime.reconnecting')
              }
            >
              <span
                className={`mr-1.5 inline-block size-1.5 rounded-full ${
                  wsLive
                    ? 'bg-emerald-500'
                    : 'bg-muted-foreground/60 animate-pulse'
                }`}
              />
              {wsLive ? t('realtime.connected') : t('realtime.reconnecting')}
            </span>
          ) : null}
        </div>
        <Can object='devices' action='create'>
          <RegisterDeviceDialog
            relayAgents={relayAgents ?? []}
            registeredSerials={registeredSerials}
          />
        </Can>
      </div>

      <FleetStatsSummary
        stats={fleetStats}
        devices={data}
        relayMap={relayMap}
        isLoading={fleetStatsLoading}
        isError={fleetStatsError}
      />

      {isLoading && !devices ? (
        <p className='text-sm text-muted-foreground'>{t('loading')}</p>
      ) : null}

      {!isLoading && !devices?.length && (
        <Can
          object='devices'
          action='create'
          fallback={
            <CoreEmptyState
              icon={Smartphone}
              title={tEmpty('fleet.title')}
              description={tEmpty('fleet.description')}
              readOnlyHint={tEmpty('readOnlyHint')}
              trackingKey='devices-list-empty-readonly'
            />
          }
        >
          <CoreEmptyState
            icon={Smartphone}
            title={tEmpty('fleet.title')}
            description={tEmpty('fleet.description')}
            trackingKey='devices-list-empty'
            cta={{ label: tEmpty('fleet.ctaPair'), href: ROUTES.DEVICES.MANAGE }}
            secondaryCta={{
              label: tEmpty('fleet.ctaRelay'),
              href: ROUTES.RELAY_AGENTS.ROOT
            }}
          />
        </Can>
      )}

      {devices?.length ? (
        <DataTable table={table} total={filteredSortedData.length}>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <div className='flex flex-wrap items-center gap-2'>
              <div className='flex items-center gap-2'>
                <span className='text-xs text-muted-foreground'>
                  {t('filters.statusLabel')}
                </span>
                <Select
                  value={statusFilter}
                  onValueChange={(v) =>
                    setStatusFilter(v as DeviceFsmFilterKey)
                  }
                >
                  <SelectTrigger className='h-8 w-[180px]'>
                    <SelectValue placeholder={t('filters.statusPlaceholder')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='all'>{t('filters.statusAll')}</SelectItem>
                    <SelectItem value='transport_online'>
                      {t('filters.statusOnline')}
                    </SelectItem>
                    <SelectItem value='transport_offline'>
                      {t('filters.statusOffline')}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button
                variant='outline'
                size='sm'
                className='h-8'
                onClick={() => setSortLastSeenDesc((v) => !v)}
                title={t('filters.sortLastSeen')}
              >
                {sortLastSeenDesc ? (
                  <ArrowDownWideNarrow size={14} className='mr-1.5' />
                ) : (
                  <ArrowUpWideNarrow size={14} className='mr-1.5' />
                )}
                {t('filters.sortLastSeen')}
              </Button>
              {(statusFilter !== DEFAULT_FILTER || !sortLastSeenDesc) && (
                <Button
                  variant='ghost'
                  size='sm'
                  className='h-8'
                  onClick={() => {
                    setStatusFilter(DEFAULT_FILTER);
                    setSortLastSeenDesc(true);
                  }}
                >
                  {t('filters.reset')}
                </Button>
              )}
            </div>
            <p className='text-xs text-muted-foreground'>
              {t('filters.showing', {
                count: filteredSortedData.length,
                total: devices.length
              })}
            </p>
          </div>
        </DataTable>
      ) : null}

      {connectDevice && (
        <ConnectDialog
          device={connectDevice}
          open={!!connectDevice}
          onClose={() => setConnectDevice(null)}
          relayMap={relayMap}
          relayAgents={relayAgents ?? []}
          registeredSerials={registeredSerials}
        />
      )}
    </div>
  );
}
