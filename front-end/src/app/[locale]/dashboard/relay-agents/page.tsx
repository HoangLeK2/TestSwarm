'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { CheckSquare, Copy, KeyRound, Loader2, Plus, RefreshCw, Server, Trash2, Wifi } from 'lucide-react';
import { useFormatter, useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  devicesApi,
  relayAgentsApi,
  type DeviceOut,
  type RelayAgentOut,
  type RelayBatchJobOut,
  type RelayAgentTokenCreated,
  type RelayAgentTokenOut,
} from '@/features/devices/services/manage-api';

function RelayTokenPanel({ tokens }: { tokens: RelayAgentTokenOut[] }) {
  const qc = useQueryClient();
  const t = useTranslations('relayAgentsFeature');
  const [name, setName] = useState('');
  const [createdToken, setCreatedToken] = useState<RelayAgentTokenCreated | null>(null);

  const { mutate: createToken, isPending: isCreating } = useMutation({
    mutationFn: () => relayAgentsApi.createToken({ name }),
    onSuccess: (token) => {
      setCreatedToken(token);
      setName('');
      qc.invalidateQueries({ queryKey: ['relay-agent-tokens'] });
    },
  });

  const { mutate: revokeToken, isPending: isRevoking } = useMutation({
    mutationFn: (tokenId: string) => relayAgentsApi.revokeToken(tokenId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['relay-agent-tokens'] });
    },
  });

  return (
    <div className='rounded-lg border border-border bg-card p-4 space-y-3'>
      <div className='flex items-center justify-between gap-3'>
        <div className='flex items-center gap-2 min-w-0'>
          <KeyRound className='size-4 text-muted-foreground' />
          <h2 className='text-sm font-medium'>{t('tokens')}</h2>
        </div>
        <form
          className='flex items-center gap-2'
          onSubmit={(event) => {
            event.preventDefault();
            createToken();
          }}
        >
          <Input
            className='h-8 w-44 text-xs'
            value={name}
            placeholder={t('tokenName')}
            onChange={(event) => setName(event.target.value)}
          />
          <Button size='sm' className='h-8 px-2 text-xs' disabled={isCreating} type='submit'>
            {isCreating ? <Loader2 className='mr-1 size-3 animate-spin' /> : <Plus className='mr-1 size-3' />}
            {t('createToken')}
          </Button>
        </form>
      </div>

      {createdToken && (
        <div className='flex items-center gap-2 rounded-md bg-muted px-2 py-1.5'>
          <span className='min-w-0 flex-1 truncate font-mono text-[11px]'>{createdToken.token}</span>
          <Button
            type='button'
            size='icon'
            variant='ghost'
            className='size-7 shrink-0'
            title={t('copyToken')}
            onClick={() => {
              void navigator.clipboard?.writeText(createdToken.token);
            }}
          >
            <Copy className='size-3.5' />
          </Button>
        </div>
      )}

      <div className='flex flex-wrap gap-2'>
        {tokens.filter(token => token.status === 'active').map(token => (
          <span key={token.id} className='inline-flex items-center gap-1 rounded bg-muted px-2 py-1'>
            <span className='max-w-[180px] truncate text-[11px]'>{token.name || token.prefix}</span>
            <span className='font-mono text-[10px] text-muted-foreground'>{token.prefix}</span>
            <Button
              type='button'
              size='icon'
              variant='ghost'
              className='size-5'
              title={t('revokeToken')}
              disabled={isRevoking}
              onClick={() => revokeToken(token.id)}
            >
              <Trash2 className='size-3' />
            </Button>
          </span>
        ))}
      </div>
    </div>
  );
}

function RelayAgentCard({
  agent,
  registeredSerials,
}: {
  agent: RelayAgentOut;
  registeredSerials: Set<string>;
}) {
  const qc = useQueryClient();
  const format = useFormatter();
  const t = useTranslations('relayAgentsFeature');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  const { data: activeJob } = useQuery<RelayBatchJobOut>({
    queryKey: ['relay-agent-job', agent.relay_id, activeJobId],
    queryFn: () => relayAgentsApi.getJob(agent.relay_id, activeJobId || ''),
    enabled: !!activeJobId,
    refetchInterval: (query) => {
      const job = query.state.data as RelayBatchJobOut | undefined;
      if (!activeJobId) return false;
      if (job && ['completed', 'completed_with_errors', 'failed', 'cancelled'].includes(job.status)) {
        return false;
      }
      return 2_000;
    },
  });

  const { mutate: provisionJob, isPending: isProvisioning } = useMutation({
    mutationFn: (body: { serials?: string[]; mode?: 'selected' | 'all_visible' }) =>
      relayAgentsApi.createProvisionJob(agent.relay_id, body),
    onSuccess: (job) => {
      setActiveJobId(job.id);
      qc.invalidateQueries({ queryKey: ['relay-agents'] });
      qc.invalidateQueries({ queryKey: ['devices'] });
    },
    onError: (err) => {
      console.error('[relay-agents] provision job failed', err);
    },
  });

  const { mutate: claimConnectJob, isPending: isClaiming } = useMutation({
    mutationFn: (body: { serials?: string[]; mode?: 'selected' | 'all_visible'; connect?: boolean }) =>
      relayAgentsApi.createClaimConnectJob(agent.relay_id, body),
    onSuccess: (job) => {
      setActiveJobId(job.id);
      qc.invalidateQueries({ queryKey: ['devices'] });
      qc.invalidateQueries({ queryKey: ['relay-agents'] });
    },
    onError: (err) => {
      console.error('[relay-agents] claim-connect job failed', err);
    },
  });

  const online = agent.status === 'online';
  const realSerials = agent.serials.filter(s => !s.startsWith('pending-'));
  const selectedSerials = realSerials.filter(serial => selected.has(serial));
  const busy = isProvisioning || isClaiming;
  const terminal = activeJob && ['completed', 'completed_with_errors', 'failed', 'cancelled'].includes(activeJob.status);

  const toggleSerial = (serial: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(serial)) next.delete(serial);
      else next.add(serial);
      return next;
    });
  };

  const selectAll = () => setSelected(new Set(realSerials));

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
        <span className='inline-flex items-center gap-1 rounded bg-muted px-2 py-1 text-[11px] text-muted-foreground'>
          <Wifi className='size-3' />
          {realSerials.length}
        </span>
      </div>

      <div className='flex flex-wrap items-center gap-2'>
        <Button
          type='button'
          size='sm'
          variant='outline'
          className='h-7 px-2 text-xs'
          disabled={!online || realSerials.length === 0}
          onClick={selectAll}
        >
          <CheckSquare className='mr-1 size-3' />
          {t('selectAll')}
        </Button>
        <Button
          type='button'
          size='sm'
          variant='outline'
          className='h-7 px-2 text-xs'
          disabled={busy || !online || selectedSerials.length === 0}
          onClick={() => provisionJob({ mode: 'selected', serials: selectedSerials })}
        >
          {isProvisioning ? <Loader2 className='mr-1 size-3 animate-spin' /> : <RefreshCw className='mr-1 size-3' />}
          {t('provisionSelected')}
        </Button>
        <Button
          type='button'
          size='sm'
          variant='outline'
          className='h-7 px-2 text-xs'
          disabled={busy || !online || realSerials.length === 0}
          onClick={() => provisionJob({ mode: 'all_visible' })}
        >
          {t('provisionAll')}
        </Button>
        <Button
          type='button'
          size='sm'
          className='h-7 px-2 text-xs'
          disabled={busy || !online || selectedSerials.length === 0}
          onClick={() => claimConnectJob({ mode: 'selected', serials: selectedSerials, connect: true })}
        >
          {isClaiming ? <Loader2 className='mr-1 size-3 animate-spin' /> : <Plus className='mr-1 size-3' />}
          {t('registerConnectSelected')}
        </Button>
        <Button
          type='button'
          size='sm'
          variant='secondary'
          className='h-7 px-2 text-xs'
          disabled={busy || !online || realSerials.length === 0}
          onClick={() => claimConnectJob({ mode: 'all_visible', connect: true })}
        >
          {t('registerConnectAll')}
        </Button>
      </div>

      <div className='divide-y rounded-md border border-border'>
        {realSerials.length === 0 ? (
          <div className='p-3 text-[11px] text-muted-foreground'>{t('noDevices')}</div>
        ) : (
          realSerials.map(s => {
            const registered = registeredSerials.has(s);
            return (
              <label key={s} className='flex min-h-10 items-center gap-2 px-2 py-1.5'>
                <input
                  type='checkbox'
                  className='size-3.5 shrink-0'
                  checked={selected.has(s)}
                  onChange={() => toggleSerial(s)}
                />
                <span className='min-w-0 flex-1'>
                  <span className='block truncate text-xs'>{agent.device_names?.[s] || s}</span>
                  <span className='block truncate font-mono text-[10px] text-muted-foreground'>{s}</span>
                </span>
                <span className='shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground'>
                  {registered ? t('registered') : t('ready')}
                </span>
              </label>
            );
          })
        )}
      </div>

      {activeJob && (
        <div className='rounded-md bg-muted px-3 py-2 text-xs'>
          <div className='flex items-center justify-between gap-2'>
            <span className='font-medium'>{activeJob.kind === 'provision' ? t('provisionJob') : t('claimConnectJob')}</span>
            <span className='text-muted-foreground'>{activeJob.status}</span>
          </div>
          <div className='mt-1 text-[11px] text-muted-foreground'>
            {t('jobProgress', {
              ok: activeJob.ok,
              failed: activeJob.failed,
              pending: activeJob.pending,
              total: activeJob.total,
            })}
          </div>
          {!terminal && <Loader2 className='mt-2 size-3 animate-spin text-muted-foreground' />}
          {activeJob.items.filter(item => item.status === 'failed').slice(0, 3).map(item => (
            <div key={item.id} className='mt-1 truncate text-[11px] text-destructive'>
              {item.serial}: {item.error || item.step}
            </div>
          ))}
        </div>
      )}

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
  const { data: devices = [] } = useQuery<DeviceOut[]>({
    queryKey: ['devices'],
    queryFn: devicesApi.list,
    staleTime: 15_000,
  });
  const { data: tokens = [] } = useQuery<RelayAgentTokenOut[]>({
    queryKey: ['relay-agent-tokens'],
    queryFn: relayAgentsApi.listTokens,
    staleTime: 30_000,
  });

  const onlineCount = agents.filter(a => a.status === 'online').length;
  const registeredSerials = new Set<string>();
  for (const device of devices) {
    registeredSerials.add(device.serial);
    if (device.adb_serial) registeredSerials.add(device.adb_serial);
    if (device.adb_ip) {
      registeredSerials.add(device.adb_ip);
      registeredSerials.add(`${device.adb_ip}:${device.adb_port || 5555}`);
    }
  }

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

      <RelayTokenPanel tokens={tokens} />

      {!isLoading && agents.length === 0 && (
        <div className='rounded-lg border border-dashed border-border p-12 text-center'>
          <Server className='mx-auto mb-3 size-10 text-muted-foreground' />
          <p className='text-sm text-muted-foreground'>{t('empty')}</p>
        </div>
      )}

      {agents.length > 0 && (
        <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
          {agents.map(agent => (
            <RelayAgentCard
              key={agent.relay_id}
              agent={agent}
              registeredSerials={registeredSerials}
            />
          ))}
        </div>
      )}
    </div>
  );
}
