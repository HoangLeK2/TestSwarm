'use client';

import { useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ChevronDown,
  ChevronRight,
  Server,
  Loader2,
  Plus,
  RefreshCw
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent
} from '@/components/ui/collapsible';
import {
  relayAgentsApi,
  type DeviceOut,
  type RelayAgentOut
} from '../services/manage-api';
import { RelayAgentStatusBadge } from './relay-agent-status-badge';
import { invalidateDeviceFleetQueries } from '../hooks/use-devices';
import {
  filterRelayAgentsWithVisibleDevices,
  getRelayConnectionState,
  getVisibleRelaySerials,
  isRelayOperational
} from '../lib/relay-agent-status';

import { useResourcePermissions } from '@/features/auth/hooks/use-permission';

interface RelayAgentCardProps {
  agent: RelayAgentOut;
  registeredSerials?: Set<string>;
  onDeviceRegistered?: (device: DeviceOut) => void;
}

function RelayAgentCard({
  agent,
  registeredSerials,
  onDeviceRegistered
}: RelayAgentCardProps) {
  const qc = useQueryClient();
  const t = useTranslations('relayAgentsFeature');
  const relayPerms = useResourcePermissions('relay-agents');
  const devicePerms = useResourcePermissions('devices');
  const canBootstrap = relayPerms.canExecute;
  const canRegisterDevice = devicePerms.canCreate;

  const { mutate: bootstrapAll, isPending } = useMutation({
    mutationFn: () => relayAgentsApi.bootstrapAll(agent.relay_id),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['relay-agents'] });
      invalidateDeviceFleetQueries(qc);
      const msg =
        t('bootstrapAllResult', { ok: result.ok, total: result.total }) +
        (result.failed > 0
          ? ` — ${result.results
              .filter((r) => !r.ok)
              .map((r) => r.serial)
              .join(', ')}`
          : '');
      console.info('[relay-agents]', msg);
    },
    onError: (err) => {
      console.error('[relay-agents] bootstrap-all failed', err);
    }
  });

  const { mutate: registerDevice, isPending: isRegistering } = useMutation({
    mutationFn: (serial: string) =>
      relayAgentsApi.registerDevice(agent.relay_id, serial, { name: serial }),
    onSuccess: (device) => {
      invalidateDeviceFleetQueries(qc);
      qc.invalidateQueries({ queryKey: ['relay-agents'] });
      onDeviceRegistered?.(device);
    },
    onError: (err) => {
      console.error('[relay-agents] register device failed', err);
    }
  });

  const connectionState = getRelayConnectionState(agent, {
    busy: isPending
  });
  const online = isRelayOperational(connectionState);
  const realSerials = getVisibleRelaySerials(agent, { busy: isPending });

  return (
    <div className='flex flex-col gap-2 rounded-lg border border-border bg-card p-3'>
      <div className='flex items-center justify-between gap-2'>
        <div className='flex min-w-0 flex-wrap items-center gap-2'>
          <span className='truncate text-sm font-medium'>
            {agent.name || agent.relay_id}
          </span>
          <RelayAgentStatusBadge state={connectionState} />
          <span className='shrink-0 text-[11px] text-muted-foreground'>
            {agent.ip}
          </span>
        </div>
        {canBootstrap ? (
          <Button
            size='sm'
            variant='outline'
            className='h-7 shrink-0 px-2 text-xs'
            disabled={isPending || !online || realSerials.length === 0}
            onClick={() => bootstrapAll()}
          >
            {isPending ? (
              <Loader2 className='mr-1 size-3 animate-spin' />
            ) : (
              <RefreshCw className='mr-1 size-3' />
            )}
            {t('bootstrapAll')}
          </Button>
        ) : null}
      </div>

      <div className='flex flex-wrap gap-1'>
        {realSerials.length === 0 ? (
          <span className='text-[11px] text-muted-foreground'>
            {t('noDevices')}
          </span>
        ) : (
          realSerials.slice(0, 6).map((s) => {
            const registered = registeredSerials?.has(s) ?? false;
            const label = agent.device_names?.[s] || s;
            return (
              <span
                key={s}
                className='inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5'
              >
                <span className='max-w-[180px] truncate text-[10px]' title={s}>
                  {label}
                </span>
                {registered ? (
                  <span className='text-[10px] text-muted-foreground'>
                    {t('registered')}
                  </span>
                ) : canRegisterDevice ? (
                  <Button
                    type='button'
                    size='icon'
                    variant='ghost'
                    className='size-5'
                    disabled={!online || isRegistering}
                    title={t('registerDevice')}
                    onClick={() => registerDevice(s)}
                  >
                    {isRegistering ? (
                      <Loader2 className='size-3 animate-spin' />
                    ) : (
                      <Plus className='size-3' />
                    )}
                  </Button>
                ) : null}
              </span>
            );
          })
        )}
        {realSerials.length > 6 && (
          <span className='text-[11px] text-muted-foreground'>
            {t('moreDevices', { count: realSerials.length - 6 })}
          </span>
        )}
      </div>
    </div>
  );
}

interface RelayAgentsPanelProps {
  agents: RelayAgentOut[];
  registeredSerials?: Set<string>;
  onDeviceRegistered?: (device: DeviceOut) => void;
}

export function RelayAgentsPanel({
  agents,
  registeredSerials,
  onDeviceRegistered
}: RelayAgentsPanelProps) {
  const t = useTranslations('relayAgentsFeature');
  const [open, setOpen] = useState(false);
  const didAutoOpen = useRef(false);
  const agentsWithDevices = filterRelayAgentsWithVisibleDevices(agents);
  const hasOnline = agentsWithDevices.some(
    (a) => getRelayConnectionState(a) === 'connected'
  );

  useEffect(() => {
    if (hasOnline && !didAutoOpen.current) {
      didAutoOpen.current = true;
      setOpen(true);
    }
  }, [hasOnline]);

  const connectedCount = agentsWithDevices.filter(
    (a) => getRelayConnectionState(a) === 'connected'
  ).length;

  if (agentsWithDevices.length === 0) return null;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button className='flex w-full items-center gap-2 rounded-md px-1 py-1 text-sm font-medium text-foreground transition-colors hover:bg-muted/50'>
          {open ? (
            <ChevronDown className='size-4 text-muted-foreground' />
          ) : (
            <ChevronRight className='size-4 text-muted-foreground' />
          )}
          <Server className='size-4 text-muted-foreground' />
          <span>{t('title')}</span>
          <span className='rounded-full bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground'>
            {t('onlineSummary', {
              connected: connectedCount,
              total: agentsWithDevices.length
            })}
          </span>
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className='mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3'>
          {agentsWithDevices.map((agent) => (
            <RelayAgentCard
              key={agent.relay_id}
              agent={agent}
              registeredSerials={registeredSerials}
              onDeviceRegistered={onDeviceRegistered}
            />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
