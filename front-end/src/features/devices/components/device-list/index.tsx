'use client';

import { useMemo, useState } from 'react';
import { Smartphone } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import type { DeviceOut, RelayAgentOut } from '../../services/manage-api';
import { relayAgentsApi } from '../../services/manage-api';
import { useDevices } from '../../hooks/use-devices';
import { RegisterDeviceDialog } from '../register-device-dialog';
import { DataTable } from '@/components/ui/table/data-table';
import { useDataTable } from '@/hooks/use-data-table';
import { isDeviceOnlineForList } from '../../lib/device-online';
import { getDeviceColumns } from './columns';
import { ConnectDialog } from './ConnectDialog';
import { useTranslations } from 'next-intl';
import { useConfirm } from '@/providers/modal-provider';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { ArrowDownWideNarrow, ArrowUpWideNarrow } from 'lucide-react';

export function DeviceList() {
  const t = useTranslations('devicesList');
  const tCommon = useTranslations('common');
  const confirm = useConfirm();
  const { data: devices, isLoading, error } = useDevices();
  const [connectDevice, setConnectDevice] = useState<DeviceOut | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<
    'all' | 'online' | 'offline'
  >('all');
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
        // TCP serial "ip:port" → also index by ip alone so USB-serial devices match
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

    const filtered =
      statusFilter === 'all'
        ? data
        : data.filter((d) =>
            statusFilter === 'online' ? isOnline(d) : !isOnline(d)
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
        confirm
      }),
    [deletingId, t, tCommon, relayMap, confirm]
  );

  const { table } = useDataTable<DeviceOut>({
    data: filteredSortedData,
    columns,
    pageCount: 1
  });

  if (isLoading)
    return <p className='text-sm text-muted-foreground'>{t('loading')}</p>;
  if (error)
    return <p className='text-sm text-destructive'>{t('loadError')}</p>;

  return (
    <div className='space-y-4'>
      <div className='flex items-center justify-between'>
        <h2 className='text-lg font-semibold'>
          {t('title', { count: devices?.length ?? 0 })}
        </h2>
        <RegisterDeviceDialog
          relayAgents={relayAgents ?? []}
          registeredSerials={registeredSerials}
        />
      </div>

      {!devices?.length && (
        <div className='rounded-lg border border-dashed border-border p-12 text-center'>
          <Smartphone className='mx-auto mb-3 size-10 text-muted-foreground' />
          <p className='text-sm text-muted-foreground'>
            {t.rich('emptyDescription', {
              strong: (chunks) => <strong>{chunks}</strong>
            })}
          </p>
        </div>
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
                    setStatusFilter(v as typeof statusFilter)
                  }
                >
                  <SelectTrigger className='h-8 w-[160px]'>
                    <SelectValue placeholder={t('filters.statusPlaceholder')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='all'>
                      {t('filters.statusAll')}
                    </SelectItem>
                    <SelectItem value='online'>
                      {t('filters.statusOnline')}
                    </SelectItem>
                    <SelectItem value='offline'>
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
              {(statusFilter !== 'all' || !sortLastSeenDesc) && (
                <Button
                  variant='ghost'
                  size='sm'
                  className='h-8'
                  onClick={() => {
                    setStatusFilter('all');
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
