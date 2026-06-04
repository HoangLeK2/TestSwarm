'use client';

import { Badge } from '@/components/ui/badge';
import { useTranslations } from 'next-intl';
import type {
  DeviceOut,
  FleetStatsOut,
  RelayAgentOut
} from '../../services/manage-api';
import { computeDeviceTransportCounts } from '../../lib/device-online';

/** FSM states worth surfacing in the operator summary (not transport). */
const FSM_SUMMARY_STATES = ['busy', 'dead'] as const;

export function FleetStatsSummary({
  stats,
  devices,
  relayMap,
  isLoading,
  isError
}: {
  stats: FleetStatsOut | undefined;
  devices: DeviceOut[];
  relayMap: Record<string, RelayAgentOut>;
  isLoading?: boolean;
  isError?: boolean;
}) {
  const t = useTranslations('devicesList');

  if (isLoading && !stats && !devices.length) {
    return (
      <div className='h-10 animate-pulse rounded-lg border border-border bg-muted/30' />
    );
  }

  if (isError && !stats && !devices.length) {
    return (
      <p className='text-xs text-destructive'>{t('fleetStats.loadError')}</p>
    );
  }

  const transport = computeDeviceTransportCounts(devices, relayMap);
  const total = transport.total || stats?.devices.total || 0;
  const sessions = stats?.active_sessions;

  if (total === 0) return null;

  return (
    <div className='space-y-2 rounded-lg border border-border bg-muted/30 px-3 py-2'>
      <div className='flex flex-wrap items-center gap-2'>
        <span className='text-xs font-medium text-muted-foreground'>
          {t('fleetStats.title', { total })}
        </span>
        {transport.online > 0 ? (
          <Badge variant='default' className='text-[10px] font-normal'>
            {t('filters.statusOnline')}: {transport.online}
          </Badge>
        ) : null}
        {transport.offline > 0 ? (
          <Badge variant='outline' className='text-[10px] font-normal'>
            {t('filters.statusOffline')}: {transport.offline}
          </Badge>
        ) : null}
        {stats
          ? FSM_SUMMARY_STATES.map((state) => {
              const n = stats.devices[state] ?? 0;
              if (n === 0) return null;
              return (
                <Badge
                  key={state}
                  variant={state === 'dead' ? 'destructive' : 'secondary'}
                  className='text-[10px] font-normal'
                >
                  {t(`fsm.${state}`)}: {n}
                </Badge>
              );
            })
          : null}
      </div>
      {sessions && sessions.total > 0 ? (
        <div className='flex flex-wrap items-center gap-2 border-t border-border/60 pt-2'>
          <span className='text-xs text-muted-foreground'>
            {t('fleetStats.activeSessions', { total: sessions.total })}
          </span>
          {(
            [
              ['user', sessions.user],
              ['execution', sessions.execution],
              ['campaign', sessions.campaign],
              ['system', sessions.system],
              ['unknown', sessions.unknown]
            ] as const
          ).map(([key, n]) =>
            n > 0 ? (
              <Badge
                key={key}
                variant='secondary'
                className='text-[10px] font-normal'
              >
                {t(`fleetStats.sessionOwner.${key}`)}: {n}
              </Badge>
            ) : null
          )}
        </div>
      ) : null}
    </div>
  );
}
