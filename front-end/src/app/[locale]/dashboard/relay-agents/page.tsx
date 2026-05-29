'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  CheckSquare,
  Copy,
  KeyRound,
  Loader2,
  Plus,
  RefreshCw,
  Server,
  Trash2,
  Wifi
} from 'lucide-react';
import { useFormatter, useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import {
  devicesApi,
  relayAgentsApi,
  type DeviceOut,
  type RelayAgentOut,
  type RelayBatchJobOut,
  type RelayAgentTokenCreated,
  type RelayAgentTokenOut
} from '@/features/devices/services/manage-api';

function RelayTokenSection({ tokens }: { tokens: RelayAgentTokenOut[] }) {
  const qc = useQueryClient();
  const t = useTranslations('relayAgentsFeature');
  const format = useFormatter();
  const [createOpen, setCreateOpen] = useState(false);
  const [createdOpen, setCreatedOpen] = useState(false);
  const [revokeId, setRevokeId] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [createdToken, setCreatedToken] =
    useState<RelayAgentTokenCreated | null>(null);

  const activeTokens = tokens.filter((token) => token.status === 'active');

  const { mutate: createToken, isPending: isCreating } = useMutation({
    mutationFn: () => relayAgentsApi.createToken({ name }),
    onSuccess: (token) => {
      setCreatedToken(token);
      setName('');
      setCreateOpen(false);
      setCreatedOpen(true);
      qc.invalidateQueries({ queryKey: ['relay-agent-tokens'] });
    }
  });

  const { mutate: revokeToken, isPending: isRevoking } = useMutation({
    mutationFn: (tokenId: string) => relayAgentsApi.revokeToken(tokenId),
    onSuccess: () => {
      setRevokeId(null);
      qc.invalidateQueries({ queryKey: ['relay-agent-tokens'] });
    }
  });

  const copyToken = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(t('copySuccess'));
    } catch {
      toast.error(t('copyToken'));
    }
  };

  return (
    <>
      <div className='rounded-lg border border-border bg-card'>
        <div className='flex flex-col gap-4 border-b border-border p-4 sm:flex-row sm:items-start sm:justify-between'>
          <div className='flex min-w-0 gap-3'>
            <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
              <KeyRound className='size-4 text-muted-foreground' />
            </div>
            <div className='min-w-0 space-y-1'>
              <h2 className='text-sm font-semibold'>{t('tokens')}</h2>
              <p className='text-xs text-muted-foreground'>
                {t('tokensDescription')}
              </p>
            </div>
          </div>
          <Button
            size='sm'
            className='shrink-0'
            onClick={() => setCreateOpen(true)}
          >
            <Plus className='mr-1.5 size-3.5' />
            {t('createToken')}
          </Button>
        </div>

        {activeTokens.length === 0 ? (
          <p className='p-4 text-sm text-muted-foreground'>
            {t('noActiveTokens')}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('colTokenName')}</TableHead>
                <TableHead>{t('colTokenPrefix')}</TableHead>
                <TableHead className='hidden sm:table-cell'>
                  {t('colTokenCreated')}
                </TableHead>
                <TableHead className='w-[72px] text-right' />
              </TableRow>
            </TableHeader>
            <TableBody>
              {activeTokens.map((token) => (
                <TableRow key={token.id}>
                  <TableCell className='font-medium'>
                    {token.name?.trim() || '—'}
                  </TableCell>
                  <TableCell>
                    <code className='rounded bg-muted px-1.5 py-0.5 text-xs'>
                      {token.prefix}
                    </code>
                  </TableCell>
                  <TableCell className='hidden text-muted-foreground sm:table-cell'>
                    {token.created_at
                      ? format.dateTime(new Date(token.created_at), {
                          dateStyle: 'short',
                          timeStyle: 'short'
                        })
                      : '—'}
                  </TableCell>
                  <TableCell className='text-right'>
                    <Button
                      type='button'
                      size='icon'
                      variant='ghost'
                      className='size-8 text-destructive hover:text-destructive'
                      title={t('revokeToken')}
                      disabled={isRevoking}
                      onClick={() => setRevokeId(token.id)}
                    >
                      <Trash2 className='size-3.5' />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className='sm:max-w-md'>
          <DialogHeader>
            <DialogTitle>{t('createTokenDialogTitle')}</DialogTitle>
            <DialogDescription>
              {t('createTokenDialogDescription')}
            </DialogDescription>
          </DialogHeader>
          <form
            className='space-y-4'
            onSubmit={(event) => {
              event.preventDefault();
              createToken();
            }}
          >
            <div className='space-y-2'>
              <label className='text-sm font-medium' htmlFor='relay-token-name'>
                {t('tokenName')}
              </label>
              <Input
                id='relay-token-name'
                value={name}
                placeholder={t('tokenNamePlaceholder')}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <DialogFooter>
              <Button
                type='button'
                variant='outline'
                onClick={() => setCreateOpen(false)}
              >
                {t('cancel')}
              </Button>
              <Button type='submit' disabled={isCreating}>
                {isCreating && (
                  <Loader2 className='mr-1.5 size-3.5 animate-spin' />
                )}
                {t('createToken')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={createdOpen} onOpenChange={setCreatedOpen}>
        <DialogContent className='sm:max-w-lg'>
          <DialogHeader>
            <DialogTitle>{t('tokenCreatedDialogTitle')}</DialogTitle>
            <DialogDescription>
              {t('tokenCreatedDialogDescription')}
            </DialogDescription>
          </DialogHeader>
          {createdToken && (
            <div className='flex items-center gap-2 rounded-md border border-border bg-muted/50 p-3'>
              <code className='min-w-0 flex-1 break-all text-xs'>
                {createdToken.token}
              </code>
              <Button
                type='button'
                size='icon'
                variant='outline'
                className='size-8 shrink-0'
                title={t('copyToken')}
                onClick={() => void copyToken(createdToken.token)}
              >
                <Copy className='size-3.5' />
              </Button>
            </div>
          )}
          <DialogFooter>
            <Button
              type='button'
              onClick={() => {
                setCreatedOpen(false);
                setCreatedToken(null);
              }}
            >
              {t('tokenCreatedClose')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={!!revokeId}
        onOpenChange={(open) => !open && setRevokeId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('revokeTokenTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('revokeTokenDescription')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className='bg-destructive text-white hover:bg-destructive/90'
              disabled={isRevoking}
              onClick={() => revokeId && revokeToken(revokeId)}
            >
              {t('revokeToken')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function RelayAgentCard({
  agent,
  registeredSerials
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
      if (
        job &&
        ['completed', 'completed_with_errors', 'failed', 'cancelled'].includes(
          job.status
        )
      ) {
        return false;
      }
      return 2_000;
    }
  });

  const { mutate: provisionJob, isPending: isProvisioning } = useMutation({
    mutationFn: (body: {
      serials?: string[];
      mode?: 'selected' | 'all_visible';
    }) => relayAgentsApi.createProvisionJob(agent.relay_id, body),
    onSuccess: (job) => {
      setActiveJobId(job.id);
      qc.invalidateQueries({ queryKey: ['relay-agents'] });
      qc.invalidateQueries({ queryKey: ['devices'] });
    },
    onError: (err) => {
      console.error('[relay-agents] provision job failed', err);
    }
  });

  const { mutate: claimConnectJob, isPending: isClaiming } = useMutation({
    mutationFn: (body: {
      serials?: string[];
      mode?: 'selected' | 'all_visible';
      connect?: boolean;
    }) => relayAgentsApi.createClaimConnectJob(agent.relay_id, body),
    onSuccess: (job) => {
      setActiveJobId(job.id);
      qc.invalidateQueries({ queryKey: ['devices'] });
      qc.invalidateQueries({ queryKey: ['relay-agents'] });
    },
    onError: (err) => {
      console.error('[relay-agents] claim-connect job failed', err);
    }
  });

  const online = agent.status === 'online';
  const realSerials = agent.serials.filter((s) => !s.startsWith('pending-'));
  const selectedSerials = realSerials.filter((serial) => selected.has(serial));
  const busy = isProvisioning || isClaiming;
  const terminal =
    activeJob &&
    ['completed', 'completed_with_errors', 'failed', 'cancelled'].includes(
      activeJob.status
    );

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
    <div className='flex flex-col gap-3 rounded-lg border border-border bg-card p-4'>
      <div className='flex items-start justify-between gap-2'>
        <div className='min-w-0 space-y-1'>
          <div className='flex flex-wrap items-center gap-2'>
            <p className='truncate text-sm font-semibold'>
              {agent.hostname || agent.relay_id}
            </p>
            <Badge variant={online ? 'default' : 'secondary'}>
              {online ? t('statusOnline') : t('statusOffline')}
            </Badge>
          </div>
          <p className='text-xs text-muted-foreground'>{agent.ip}</p>
          <p className='truncate font-mono text-[10px] text-muted-foreground'>
            {t('relayIdLabel')}: {agent.relay_id}
          </p>
        </div>
        <Badge variant='outline' className='shrink-0 gap-1'>
          <Wifi className='size-3' />
          {t('deviceCount', { count: realSerials.length })}
        </Badge>
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
          onClick={() =>
            provisionJob({ mode: 'selected', serials: selectedSerials })
          }
        >
          {isProvisioning ? (
            <Loader2 className='mr-1 size-3 animate-spin' />
          ) : (
            <RefreshCw className='mr-1 size-3' />
          )}
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
          onClick={() =>
            claimConnectJob({
              mode: 'selected',
              serials: selectedSerials,
              connect: true
            })
          }
        >
          {isClaiming ? (
            <Loader2 className='mr-1 size-3 animate-spin' />
          ) : (
            <Plus className='mr-1 size-3' />
          )}
          {t('registerConnectSelected')}
        </Button>
        <Button
          type='button'
          size='sm'
          variant='secondary'
          className='h-7 px-2 text-xs'
          disabled={busy || !online || realSerials.length === 0}
          onClick={() =>
            claimConnectJob({ mode: 'all_visible', connect: true })
          }
        >
          {t('registerConnectAll')}
        </Button>
      </div>

      <div className='divide-y rounded-md border border-border'>
        {realSerials.length === 0 ? (
          <div className='p-3 text-xs text-muted-foreground'>
            {t('noDevices')}
          </div>
        ) : (
          realSerials.map((s) => {
            const registered = registeredSerials.has(s);
            return (
              <label
                key={s}
                className='flex min-h-10 cursor-pointer items-center gap-2 px-2 py-1.5'
              >
                <input
                  type='checkbox'
                  className='size-3.5 shrink-0'
                  checked={selected.has(s)}
                  onChange={() => toggleSerial(s)}
                />
                <span className='min-w-0 flex-1'>
                  <span className='block truncate text-xs'>
                    {agent.device_names?.[s] || s}
                  </span>
                  <span className='block truncate font-mono text-[10px] text-muted-foreground'>
                    {s}
                  </span>
                </span>
                <Badge
                  variant={registered ? 'secondary' : 'outline'}
                  className='shrink-0 text-[10px]'
                >
                  {registered ? t('registered') : t('ready')}
                </Badge>
              </label>
            );
          })
        )}
      </div>

      {activeJob && (
        <div className='rounded-md bg-muted px-3 py-2 text-xs'>
          <div className='flex items-center justify-between gap-2'>
            <span className='font-medium'>
              {activeJob.kind === 'provision'
                ? t('provisionJob')
                : t('claimConnectJob')}
            </span>
            <span className='text-muted-foreground'>{activeJob.status}</span>
          </div>
          <div className='mt-1 text-[11px] text-muted-foreground'>
            {t('jobProgress', {
              ok: activeJob.ok,
              failed: activeJob.failed,
              pending: activeJob.pending,
              total: activeJob.total
            })}
          </div>
          {!terminal && (
            <Loader2 className='mt-2 size-3 animate-spin text-muted-foreground' />
          )}
          {activeJob.items
            .filter((item) => item.status === 'failed')
            .slice(0, 3)
            .map((item) => (
              <div
                key={item.id}
                className='mt-1 truncate text-[11px] text-destructive'
              >
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
    refetchInterval: 30_000
  });
  const { data: devices = [] } = useQuery<DeviceOut[]>({
    queryKey: ['devices'],
    queryFn: devicesApi.list,
    staleTime: 15_000
  });
  const { data: tokens = [] } = useQuery<RelayAgentTokenOut[]>({
    queryKey: ['relay-agent-tokens'],
    queryFn: relayAgentsApi.listTokens,
    staleTime: 30_000
  });

  const onlineCount = agents.filter((a) => a.status === 'online').length;
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
      <div className='flex items-start gap-3'>
        <Server className='mt-0.5 size-5 shrink-0 text-muted-foreground' />
        <div className='min-w-0'>
          <h1 className='text-xl font-semibold'>{t('title')}</h1>
          <p className='text-sm text-muted-foreground'>{t('subtitle')}</p>
          {!isLoading && agents.length > 0 && (
            <p className='mt-1 text-sm text-muted-foreground'>
              {t('onlineSummary', {
                online: onlineCount,
                total: agents.length
              })}
            </p>
          )}
        </div>
      </div>

      {isLoading && (
        <p className='text-sm text-muted-foreground'>{t('loading')}</p>
      )}

      <RelayTokenSection tokens={tokens} />

      {!isLoading && agents.length === 0 && (
        <div className='rounded-lg border border-dashed border-border p-12 text-center'>
          <Server className='mx-auto mb-3 size-10 text-muted-foreground' />
          <p className='text-sm font-medium text-muted-foreground'>
            {t('empty')}
          </p>
          <p className='mt-2 text-xs text-muted-foreground'>{t('emptyHint')}</p>
        </div>
      )}

      {agents.length > 0 && (
        <>
          <p className='text-xs text-muted-foreground'>{t('dedupeHint')}</p>
          <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
            {agents.map((agent) => (
              <RelayAgentCard
                key={agent.relay_id}
                agent={agent}
                registeredSerials={registeredSerials}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
