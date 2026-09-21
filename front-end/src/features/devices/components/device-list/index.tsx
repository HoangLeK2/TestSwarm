'use client';

import { useEffect, useMemo, useState } from 'react';
import { Smartphone } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import type {
  DeviceListParams,
  DeviceOut,
  RelayAgentOut
} from '../../services/manage-api';
import { devicesApi, relayAgentsApi } from '../../services/manage-api';
import {
  useDevicePage,
  useDevices,
  useFleetStats
} from '../../hooks/use-devices';
import { useDeviceListRealtime } from '../../hooks/use-device-list-realtime';
import { useLifecycleWsConnected } from '../../lib/lifecycle-ws-store';
import { RegisterDeviceDialog } from '../register-device-dialog';
import { DataTable } from '@/components/ui/table/data-table';
import { useDataTable } from '@/hooks/use-data-table';
import type { DeviceFsmStateKey } from '../../lib/device-fsm';
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
import { Input } from '@/components/ui/input';
import { useDebouncedCallback } from '@/hooks/use-debounced-callback';
import { parseAsInteger, useQueryStates } from 'nuqs';

type ServerDeviceStatusFilter = 'all' | DeviceFsmStateKey;

const DEFAULT_FILTER: ServerDeviceStatusFilter = 'all';
const DEFAULT_PAGE_SIZE = 10;

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

  const [{ page, perPage }, setPagination] = useQueryStates({
    page: parseAsInteger.withDefault(1),
    perPage: parseAsInteger.withDefault(DEFAULT_PAGE_SIZE)
  });
  const { data: allDevices } = useDevices();
  const {
    data: fleetStats,
    isLoading: fleetStatsLoading,
    isError: fleetStatsError
  } = useFleetStats();
  const [connectDevice, setConnectDevice] = useState<DeviceOut | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] =
    useState<ServerDeviceStatusFilter>(DEFAULT_FILTER);
  const [sortLastSeenDesc, setSortLastSeenDesc] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('');
  const updateSearch = useDebouncedCallback((value: string) => {
    setDebouncedSearchQuery(value.trim());
  }, 300);
  const pageParams = useMemo<DeviceListParams>(
    () => ({
      page,
      pageSize: perPage,
      q: debouncedSearchQuery || undefined,
      state: statusFilter === 'all' ? undefined : statusFilter,
      sort: sortLastSeenDesc ? '-last_seen_at' : 'last_seen_at'
    }),
    [debouncedSearchQuery, page, perPage, sortLastSeenDesc, statusFilter]
  );
  const {
    data: devicePage,
    isLoading,
    error,
    refetch
  } = useDevicePage(pageParams);

  const { data: relayAgents } = useQuery<RelayAgentOut[]>({
    queryKey: ['relay-agents'],
    queryFn: relayAgentsApi.list,
    staleTime: 15_000,
    refetchInterval: 30_000
  });
  const { data: allocatedDevices = [] } = useQuery<DeviceOut[]>({
    queryKey: ['devices', 'allocated', 'banner'],
    queryFn: () => devicesApi.listAllocated({ limit: 20 }),
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

  const data: DeviceOut[] = useMemo(
    () => devicePage?.items ?? [],
    [devicePage?.items]
  );
  const totalDevices = devicePage?.total ?? 0;
  const pageCount = Math.max(1, devicePage?.page_count ?? 1);
  const hasActiveFilter =
    debouncedSearchQuery.length > 0 || statusFilter !== DEFAULT_FILTER;
  const fleetDevices = allDevices ?? data;

  useEffect(() => {
    if (page > pageCount) void setPagination({ page: pageCount });
  }, [page, pageCount, setPagination]);

  const registeredSerials = useMemo(() => {
    const serials = new Set<string>();
    for (const device of allDevices ?? []) {
      serials.add(device.serial);
      if (device.adb_serial) serials.add(device.adb_serial);
    }
    return serials;
  }, [allDevices]);

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
    data,
    columns,
    pageCount,
    initialState: {
      pagination: { pageIndex: 0, pageSize: DEFAULT_PAGE_SIZE }
    }
  });

  if (error && !devicePage)
    return (
      <div className='rounded-md border border-destructive/30 bg-destructive/5 p-4'>
        <p className='text-sm font-medium text-destructive'>{t('loadError')}</p>
        <Button
          type='button'
          variant='outline'
          size='sm'
          className='mt-3'
          onClick={() => void refetch()}
        >
          {tCommon('retry')}
        </Button>
      </div>
    );

  return (
    <div className='space-y-5'>
      <div className='flex items-center justify-between gap-3'>
        <div className='min-w-0'>
          <div className='flex flex-wrap items-center gap-2'>
            <h2 className='text-xl font-semibold tracking-tight'>
              {t('title', { count: totalDevices })}
            </h2>
            {user ? (
              <span
                className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${
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
                      : 'animate-pulse bg-muted-foreground/60'
                  }`}
                />
                {wsLive ? t('realtime.connected') : t('realtime.reconnecting')}
              </span>
            ) : null}
          </div>
          <p className='mt-1 text-sm text-muted-foreground'>
            {t('description')}
          </p>
        </div>
        <Can object='devices' action='create'>
          <RegisterDeviceDialog
            relayAgents={relayAgents ?? []}
            registeredSerials={registeredSerials}
          />
        </Can>
      </div>

      {allocatedDevices.length > 0 ? (
        <Can object='devices' action='create'>
          <section className='flex flex-col gap-3 rounded-md border bg-background p-4 md:flex-row md:items-center md:justify-between'>
            <div>
              <h3 className='text-sm font-semibold'>
                {t('allocatedBanner.title', { count: allocatedDevices.length })}
              </h3>
              <p className='mt-1 text-sm text-muted-foreground'>
                {t('allocatedBanner.description')}
              </p>
            </div>
            <RegisterDeviceDialog
              relayAgents={relayAgents ?? []}
              registeredSerials={registeredSerials}
            />
          </section>
        </Can>
      ) : null}

      <FleetStatsSummary
        stats={fleetStats}
        devices={fleetDevices}
        relayMap={relayMap}
        isLoading={fleetStatsLoading}
        isError={fleetStatsError}
      />

      {isLoading && !devicePage ? (
        <p className='text-sm text-muted-foreground'>{t('loading')}</p>
      ) : null}

      {!isLoading && totalDevices === 0 && !hasActiveFilter && (
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
            cta={{
              label: tEmpty('fleet.ctaPair'),
              href: ROUTES.DEVICES.MANAGE
            }}
            secondaryCta={{
              label: tEmpty('fleet.ctaRelay'),
              href: ROUTES.RELAY_AGENTS.ROOT
            }}
          />
        </Can>
      )}

      {totalDevices > 0 || hasActiveFilter ? (
        <DataTable table={table} total={totalDevices}>
          <div className='border-b pb-3'>
            <div className='flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between'>
              <div className='flex flex-1 flex-col gap-2 sm:flex-row'>
                <Input
                  value={searchQuery}
                  onChange={(event) => {
                    const next = event.target.value;
                    setSearchQuery(next);
                    updateSearch(next);
                    void setPagination({ page: 1 });
                  }}
                  placeholder={t('filters.searchPlaceholder')}
                  aria-label={t('filters.searchLabel')}
                  className='h-9 w-full sm:max-w-md'
                />
                <Select
                  value={statusFilter}
                  onValueChange={(v) => {
                    setStatusFilter(v as ServerDeviceStatusFilter);
                    void setPagination({ page: 1 });
                  }}
                >
                  <SelectTrigger className='h-9 w-full sm:w-[180px]'>
                    <SelectValue placeholder={t('filters.statusPlaceholder')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='all'>
                      {t('filters.statusAll')}
                    </SelectItem>
                    <SelectItem value='online'>
                      {t('fsm.online' as `fsm.${DeviceFsmStateKey}`)}
                    </SelectItem>
                    <SelectItem value='busy'>
                      {t('fsm.busy' as `fsm.${DeviceFsmStateKey}`)}
                    </SelectItem>
                    <SelectItem value='reconnecting'>
                      {t('fsm.reconnecting' as `fsm.${DeviceFsmStateKey}`)}
                    </SelectItem>
                    <SelectItem value='dead'>
                      {t('fsm.dead' as `fsm.${DeviceFsmStateKey}`)}
                    </SelectItem>
                    <SelectItem value='unknown'>
                      {t('fsm.unknown' as `fsm.${DeviceFsmStateKey}`)}
                    </SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  variant='outline'
                  size='sm'
                  className='h-9 justify-start sm:justify-center'
                  onClick={() => {
                    setSortLastSeenDesc((v) => !v);
                    void setPagination({ page: 1 });
                  }}
                  title={t('filters.sortLastSeen')}
                >
                  {sortLastSeenDesc
                    ? t('filters.sortNewest')
                    : t('filters.sortOldest')}
                </Button>
                {(searchQuery ||
                  statusFilter !== DEFAULT_FILTER ||
                  !sortLastSeenDesc) && (
                  <Button
                    variant='ghost'
                    size='sm'
                    className='h-9'
                    onClick={() => {
                      setSearchQuery('');
                      setDebouncedSearchQuery('');
                      setStatusFilter(DEFAULT_FILTER);
                      setSortLastSeenDesc(true);
                      void setPagination({ page: 1 });
                    }}
                  >
                    {t('filters.reset')}
                  </Button>
                )}
              </div>
              <p className='shrink-0 text-xs text-muted-foreground'>
                {t('filters.showing', {
                  count: data.length,
                  total: totalDevices
                })}
              </p>
            </div>
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
