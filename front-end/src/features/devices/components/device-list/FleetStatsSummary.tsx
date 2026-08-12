'use client';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { useState } from 'react';
import { useTranslations } from 'next-intl';
import type {
  DeviceOut,
  FleetStatsOut,
  RelayAgentOut
} from '../../services/manage-api';
import { devicesApi } from '../../services/manage-api';
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
  const [showSessions, setShowSessions] = useState(false);
  const sessionDetails = useQuery({
    queryKey: ['devices', 'fleet', 'active-sessions'],
    queryFn: () => devicesApi.activeSessions(),
    enabled: showSessions,
    staleTime: 10_000
  });

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
  const deviceCounts = stats?.devices;
  const total = transport.total || deviceCounts?.total || 0;
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
        {deviceCounts
          ? FSM_SUMMARY_STATES.map((state) => {
              const n = deviceCounts[state] ?? 0;
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
          <Button
            type='button'
            variant='ghost'
            size='sm'
            className='ml-auto h-7 text-xs'
            onClick={() => setShowSessions((value) => !value)}
            aria-expanded={showSessions}
          >
            {showSessions ? (
              <ChevronUp className='mr-1 size-3.5' />
            ) : (
              <ChevronDown className='mr-1 size-3.5' />
            )}
            {t('fleetStats.viewSessions')}
          </Button>
        </div>
      ) : null}
      {showSessions ? (
        <div className='border-t border-border/60 pt-2'>
          <p className='mb-2 text-[11px] text-muted-foreground'>
            {t('fleetStats.sessionExplanation')}
          </p>
          {sessionDetails.isLoading ? (
            <div className='h-14 animate-pulse rounded bg-muted/50' />
          ) : sessionDetails.isError ? (
            <p className='text-xs text-destructive'>
              {t('fleetStats.sessionLoadError')}
            </p>
          ) : (
            <div className='max-h-48 divide-y overflow-auto rounded border bg-background'>
              {(sessionDetails.data?.sessions ?? []).map((session) => (
                <div
                  key={session.session_id}
                  className='flex items-center gap-2 px-2 py-2 text-xs'
                >
                  <div className='min-w-0 flex-1'>
                    <p className='truncate font-medium'>
                      {session.device_name}
                    </p>
                    <p className='truncate font-mono text-[10px] text-muted-foreground'>
                      {session.device_serial}
                    </p>
                  </div>
                  <Badge
                    variant='secondary'
                    className='text-[10px] font-normal'
                  >
                    {t(`fleetStats.sessionOwner.${session.owner_type}`)}
                  </Badge>
                  {session.duplicate_for_device ? (
                    <Badge
                      variant='outline'
                      className='border-amber-500/40 text-[10px] text-amber-700 dark:text-amber-300'
                    >
                      {t('fleetStats.duplicateSession')}
                    </Badge>
                  ) : null}
                  {session.source === 'busy_claim' ? (
                    <Badge variant='outline' className='text-[10px]'>
                      {t('fleetStats.busyClaim')}
                    </Badge>
                  ) : null}
                  <time className='shrink-0 text-[10px] text-muted-foreground'>
                    {new Intl.DateTimeFormat(undefined, {
                      dateStyle: 'short',
                      timeStyle: 'short'
                    }).format(new Date(session.created_at))}
                  </time>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
