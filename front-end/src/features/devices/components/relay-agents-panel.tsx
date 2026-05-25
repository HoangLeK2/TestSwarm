'use client';

import { useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, Server, Loader2, Plus, RefreshCw } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { relayAgentsApi, type DeviceOut, type RelayAgentOut } from '../services/manage-api';

interface RelayAgentCardProps {
  agent: RelayAgentOut;
  registeredSerials?: Set<string>;
  onDeviceRegistered?: (device: DeviceOut) => void;
}

function RelayAgentCard({ agent, registeredSerials, onDeviceRegistered }: RelayAgentCardProps) {
  const qc = useQueryClient();
  const t = useTranslations('relayAgentsFeature');

  const { mutate: bootstrapAll, isPending } = useMutation({
    mutationFn: () => relayAgentsApi.bootstrapAll(agent.relay_id),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['relay-agents'] });
      qc.invalidateQueries({ queryKey: ['devices'] });
      const msg = `Bootstrap: ${result.ok}/${result.total} OK` +
        (result.failed > 0
          ? ` — failed: ${result.results.filter(r => !r.ok).map(r => r.serial).join(', ')}`
          : '');
      console.info('[relay-agents]', msg);
    },
    onError: (err) => {
      console.error('[relay-agents] bootstrap-all failed', err);
    },
  });

  const { mutate: registerDevice, isPending: isRegistering } = useMutation({
    mutationFn: (serial: string) =>
      relayAgentsApi.registerDevice(agent.relay_id, serial, { name: serial }),
    onSuccess: (device) => {
      qc.invalidateQueries({ queryKey: ['devices'] });
      qc.invalidateQueries({ queryKey: ['relay-agents'] });
      onDeviceRegistered?.(device);
    },
    onError: (err) => {
      console.error('[relay-agents] register device failed', err);
    },
  });

  const online = agent.status === 'online';
  const realSerials = agent.serials.filter(s => !s.startsWith('pending-'));

  return (
    <div className='rounded-lg border border-border bg-card p-3 flex flex-col gap-2'>
      <div className='flex items-center justify-between gap-2'>
        <div className='flex items-center gap-2 min-w-0'>
          <span className={`size-2 shrink-0 rounded-full ${online ? 'bg-green-500' : 'bg-gray-400'}`} />
          <span className='font-medium text-sm truncate'>{agent.hostname || agent.relay_id}</span>
          <span className='text-[11px] text-muted-foreground shrink-0'>{agent.ip}</span>
        </div>
        <Button
          size='sm'
          variant='outline'
          className='h-7 px-2 text-xs shrink-0'
          disabled={isPending || !online || realSerials.length === 0}
          onClick={() => bootstrapAll()}
        >
          {isPending
            ? <Loader2 className='size-3 animate-spin mr-1' />
            : <RefreshCw className='size-3 mr-1' />}
          {t('bootstrapAll')}
        </Button>
      </div>

      <div className='flex flex-wrap gap-1'>
        {realSerials.length === 0 ? (
          <span className='text-[11px] text-muted-foreground'>{t('noDevices')}</span>
        ) : (
          realSerials.slice(0, 6).map(s => {
            const registered = registeredSerials?.has(s) ?? false;
            const label = agent.device_names?.[s] || s;
            return (
              <span key={s} className='inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5'>
                <span className='max-w-[180px] truncate text-[10px]' title={s}>{label}</span>
                {registered ? (
                  <span className='text-[10px] text-muted-foreground'>{t('registered')}</span>
                ) : (
                  <Button
                    type='button'
                    size='icon'
                    variant='ghost'
                    className='size-5'
                    disabled={!online || isRegistering}
                    title={t('registerDevice')}
                    onClick={() => registerDevice(s)}
                  >
                    {isRegistering ? <Loader2 className='size-3 animate-spin' /> : <Plus className='size-3' />}
                  </Button>
                )}
              </span>
            );
          })
        )}
        {realSerials.length > 6 && (
          <span className='text-[11px] text-muted-foreground'>{t('moreDevices', { count: realSerials.length - 6 })}</span>
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

export function RelayAgentsPanel({ agents, registeredSerials, onDeviceRegistered }: RelayAgentsPanelProps) {
  const t = useTranslations('relayAgentsFeature');
  const [open, setOpen] = useState(false);
  const didAutoOpen = useRef(false);
  const hasOnline = agents.some(a => a.status === 'online');

  useEffect(() => {
    if (hasOnline && !didAutoOpen.current) {
      didAutoOpen.current = true;
      setOpen(true);
    }
  }, [hasOnline]);

  const onlineCount = agents.filter(a => a.status === 'online').length;

  if (agents.length === 0) return null;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button className='flex w-full items-center gap-2 rounded-md px-1 py-1 text-sm font-medium text-foreground hover:bg-muted/50 transition-colors'>
          {open ? <ChevronDown className='size-4 text-muted-foreground' /> : <ChevronRight className='size-4 text-muted-foreground' />}
          <Server className='size-4 text-muted-foreground' />
          <span>{t('title')}</span>
          <span className='rounded-full bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground'>
            {t('onlineSummary', { online: onlineCount, total: agents.length })}
          </span>
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className='mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3'>
          {agents.map(agent => (
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
