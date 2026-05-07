'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Server, Loader2, RefreshCw } from 'lucide-react';
import { useFormatter, useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { relayAgentsApi, type RelayAgentOut } from '@/features/devices/services/manage-api';

function RelayAgentCard({ agent }: { agent: RelayAgentOut }) {
  const qc = useQueryClient();
  const format = useFormatter();
  const t = useTranslations('relayAgentsFeature');
  const { mutate: bootstrapAll, isPending } = useMutation({
    mutationFn: () => relayAgentsApi.bootstrapAll(agent.relay_id),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['relay-agents'] });
      qc.invalidateQueries({ queryKey: ['devices'] });
      console.info(`[relay-agents] bootstrap ${result.ok}/${result.total} OK`);
    },
    onError: (err) => {
      console.error('[relay-agents] bootstrap-all failed', err);
    },
  });

  const online = agent.status === 'online';
  const realSerials = agent.serials.filter(s => !s.startsWith('pending-'));

  return (
    <div className='rounded-lg border border-border bg-card p-4 flex flex-col gap-3'>
      <div className='flex items-center justify-between gap-2'>
        <div className='flex items-center gap-2 min-w-0'>
          <span className={`size-2 shrink-0 rounded-full ${online ? 'bg-green-500' : 'bg-gray-400'}`} />
          <div className='min-w-0'>
            <p className='font-medium text-sm truncate'>{agent.hostname || agent.relay_id}</p>
            <p className='text-[11px] text-muted-foreground'>{agent.ip}</p>
          </div>
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
          realSerials.slice(0, 8).map(s => (
            <span key={s} className='rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]'>{s}</span>
          ))
        )}
        {realSerials.length > 8 && (
          <span className='text-[11px] text-muted-foreground'>{t('moreDevices', { count: realSerials.length - 8 })}</span>
        )}
      </div>

      {agent.last_heartbeat_at && (
        <p className='text-[10px] text-muted-foreground'>
          {t('lastHeartbeat', {
            time: format.dateTime(new Date(agent.last_heartbeat_at), {
              dateStyle: 'short',
              timeStyle: 'medium'
            })
          })}
        </p>
      )}
    </div>
  );
}

export default function RelayAgentsPage() {
  const t = useTranslations('relayAgentsFeature');
  const { data: agents = [], isLoading } = useQuery<RelayAgentOut[]>({
    queryKey: ['relay-agents'],
    queryFn: relayAgentsApi.list,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  const onlineCount = agents.filter(a => a.status === 'online').length;

  return (
    <div className='space-y-6'>
      <div className='flex items-center gap-3'>
        <Server className='size-5 text-muted-foreground' />
        <div>
          <h1 className='text-xl font-semibold'>{t('title')}</h1>
          {!isLoading && (
            <p className='text-sm text-muted-foreground'>
              {t('onlineSummary', { online: onlineCount, total: agents.length })}
            </p>
          )}
        </div>
      </div>

      {isLoading && (
        <p className='text-sm text-muted-foreground'>{t('loading')}</p>
      )}

      {!isLoading && agents.length === 0 && (
        <div className='rounded-lg border border-dashed border-border p-12 text-center'>
          <Server className='mx-auto mb-3 size-10 text-muted-foreground' />
          <p className='text-sm text-muted-foreground'>{t('empty')}</p>
        </div>
      )}

      {agents.length > 0 && (
        <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
          {agents.map(agent => (
            <RelayAgentCard key={agent.relay_id} agent={agent} />
          ))}
        </div>
      )}
    </div>
  );
}
