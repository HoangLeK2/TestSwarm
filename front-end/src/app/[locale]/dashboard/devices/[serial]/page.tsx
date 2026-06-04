'use client';

import { useMemo } from 'react';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { DeviceDetailView } from '@/features/devices/components/device-detail/device-detail-view';
import { fetchLiveDevices } from '@/features/devices/services/api';
import {
  relayAgentsApi,
  type RelayAgentOut
} from '@/features/devices/services/manage-api';
import type { Device } from '@/features/devices/types';

export default function DeviceDetailPage() {
  const params = useParams<{ serial: string }>();
  const serial = decodeURIComponent(params.serial ?? '');

  const { data: liveDevices } = useQuery({
    queryKey: ['devices', 'live', serial],
    queryFn: () => fetchLiveDevices({ limit: 500 }),
    enabled: Boolean(serial),
    refetchInterval: 10_000
  });

  const { data: relayAgents } = useQuery({
    queryKey: ['relay-agents'],
    queryFn: relayAgentsApi.list,
    staleTime: 15_000
  });

  const liveDevice = useMemo(
    () => liveDevices?.find((d) => d.serial === serial) ?? null,
    [liveDevices, serial]
  );

  const relayMap = useMemo(() => {
    const m: Record<string, RelayAgentOut> = {};
    for (const agent of relayAgents ?? []) {
      m[agent.relay_id] = agent;
      for (const s of agent.serials) {
        m[s] = agent;
      }
    }
    return m;
  }, [relayAgents]);

  return (
    <DeviceDetailView
      serial={serial}
      liveDevice={liveDevice as Device | null}
      relayMap={relayMap}
    />
  );
}
