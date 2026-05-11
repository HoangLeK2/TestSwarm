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
import { getDeviceColumns } from './columns';
import { ConnectDialog } from './ConnectDialog';
import { useTranslations } from 'next-intl';

export function DeviceList() {
  const t = useTranslations('devicesList');
  const { data: devices, isLoading, error } = useDevices();
  const [connectDevice, setConnectDevice] = useState<DeviceOut | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const { data: relayAgents } = useQuery<RelayAgentOut[]>({
    queryKey: ['relay-agents'],
    queryFn:  relayAgentsApi.list,
    staleTime:       15_000,
    refetchInterval: 30_000,
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

  const data: DeviceOut[] = devices ?? [];
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
        deletingId,
        setDeletingId,
        setConnectDevice,
        relayMap
      }),
    [deletingId, t, relayMap]
  );

  const { table } = useDataTable<DeviceOut>({
    data,
    columns,
    pageCount: 1
  });

  if (isLoading) return <p className='text-sm text-muted-foreground'>{t('loading')}</p>;
  if (error) return <p className='text-sm text-destructive'>{t('loadError')}</p>;

  return (
    <div className='space-y-4'>
      <div className='flex items-center justify-between'>
        <h2 className='text-lg font-semibold'>{t('title', { count: devices?.length ?? 0 })}</h2>
        <RegisterDeviceDialog relayAgents={relayAgents ?? []} registeredSerials={registeredSerials} />
      </div>

      {!devices?.length && (
        <div className='rounded-lg border border-dashed border-border p-12 text-center'>
          <Smartphone className='mx-auto mb-3 size-10 text-muted-foreground' />
          <p className='text-sm text-muted-foreground'>{t.rich('emptyDescription', { strong: (chunks) => <strong>{chunks}</strong> })}</p>
        </div>
      )}

      {devices?.length ? <DataTable table={table} total={devices.length} /> : null}

      {connectDevice && (
        <ConnectDialog device={connectDevice} open={!!connectDevice} onClose={() => setConnectDevice(null)} />
      )}
    </div>
  );
}
