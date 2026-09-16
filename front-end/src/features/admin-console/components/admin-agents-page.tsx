'use client';

import {
  type FormEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useState
} from 'react';
import {
  ArrowLeft,
  ArrowRight,
  ArrowRightLeft,
  Check,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  RotateCcw,
  Smartphone,
  Trash2
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useSearchParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from '@/components/ui/command';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
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
  ADMIN_PAGE_SIZE,
  AdminErrorState,
  AdminPageHeader,
  AdminPagination,
  AdminTableSkeleton,
  AdminWorkspaceScopeSelect,
  SearchField,
  SecretDialog,
  StatusBadge,
  SubmitSpinner
} from './admin-shared';
import { cn } from '@/lib/utils';
import { useAdminWorkspaceScope } from '../hooks/use-admin-workspace-scope';
import {
  adminApi,
  adminApiErrorCode,
  type AdminAgentOut,
  type AdminAgentPhoneOut,
  type AdminAgentUpdate,
  formatAdminApiError
} from '../services/admin-api';

// Allocation is gated per agent instead of globally: only a pool agent may hand
// phones to other workspaces (docs/device-pool-allocation.md §3), and the button
// now states that rule where it is clicked.
const PHONE_ALLOCATION_ENABLED = true;

const ALL = '__all__';
const UNASSIGNED_PHONE_FILTER = 'unassigned';
const PHONE_PAGE_SIZE = 100;
const WORKSPACE_SEARCH_LIMIT = 50;
/** While a toggle is in flight, ask often enough to feel live. */
const TOGGLE_POLL_MS = 2_000;
/** Past this, the relay host itself is the problem — stop implying we are working. */
const TOGGLE_WAIT_TIMEOUT_MS = 90_000;

function StepNumber({ children }: { children: ReactNode }) {
  return (
    <Badge
      variant='secondary'
      className='size-5 shrink-0 justify-center rounded-full p-0 text-[11px]'
    >
      {children}
    </Badge>
  );
}

function dateLabel(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '-';
}

function AgentPhonesSummary({
  agent,
  onView
}: {
  agent: AdminAgentOut;
  onView: () => void;
}) {
  const t = useTranslations('adminConsole.agents.table');
  const hasDevices = agent.deviceCount > 0 || agent.serials.length > 0;

  if (!hasDevices) {
    return (
      <span className='text-sm text-muted-foreground'>{t('noDevices')}</span>
    );
  }

  return (
    <div className='flex min-w-[120px] items-center'>
      <Button
        type='button'
        variant='outline'
        size='sm'
        className='h-8 px-2.5'
        onClick={onView}
      >
        <Smartphone className='mr-1.5 size-3.5' />
        {t('viewDevices')}
      </Button>
    </div>
  );
}

/**
 * Phones only leave an agent enrolled from a pool workspace. A tenant agent gets
 * the button disabled plus the rule and the way out, so nobody has to earn a 409
 * to learn it.
 */
function PhoneAllocationAction({
  agent,
  onOpen
}: {
  agent: AdminAgentOut;
  onOpen: () => void;
}) {
  const t = useTranslations('adminConsole.agents');
  const allowed = agent.workspaceKind === 'pool';
  const button = (
    <Button
      size='sm'
      variant='outline'
      className='h-8 px-2.5'
      disabled={!allowed}
      onClick={onOpen}
    >
      <Smartphone className='mr-1.5 size-3.5' />
      {t('actions.phones')}
    </Button>
  );

  if (allowed) return button;
  // A disabled button emits no pointer events, so the focusable span carries
  // both the hover and the keyboard path to the explanation.
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className='inline-flex' tabIndex={0}>
          {button}
        </span>
      </TooltipTrigger>
      <TooltipContent side='top' className='max-w-xs text-xs'>
        {t('phoneAllocation.tenantLocked', {
          workspace: agent.workspaceName || agent.workspaceId
        })}
      </TooltipContent>
    </Tooltip>
  );
}

export function AdminAgentsPage() {
  const t = useTranslations('adminConsole.agents');
  const qc = useQueryClient();
  const scope = useAdminWorkspaceScope();
  const searchParams = useSearchParams();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState(ALL);
  const [agentGroup, setAgentGroup] = useState<'pool' | 'workspace'>('pool');
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [editAgent, setEditAgent] = useState<AdminAgentOut | null>(null);
  const [deleteAgent, setDeleteAgent] = useState<AdminAgentOut | null>(null);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [phoneAgent, setPhoneAgent] = useState<AdminAgentOut | null>(null);
  const [viewPhonesAgent, setViewPhonesAgent] = useState<AdminAgentOut | null>(
    null
  );
  const [secret, setSecret] = useState<string | null>(null);
  const [selectedAgentIds, setSelectedAgentIds] = useState<Set<string>>(
    new Set()
  );
  const [activeTab, setActiveTab] = useState(
    searchParams.get('tab') === 'tokens' ? 'tokens' : 'agents'
  );
  // Set while a toggle has not reached the transport yet. Both directions use
  // the same watch: intent lands in the DB immediately, the fact does not, and
  // guessing which one the toast means is what misled operators.
  const [pendingToggle, setPendingToggle] = useState<{
    relayId: string;
    action: 'enable' | 'disable';
    startedAt: number;
  } | null>(null);

  const workspaceParams = { offset: 0, limit: 100 };
  const workspaces = useQuery({
    queryKey: ['admin-workspaces', workspaceParams],
    queryFn: () => adminApi.listWorkspaces(workspaceParams)
  });

  useEffect(() => {
    if (searchParams.get('tab') === 'tokens') setActiveTab('tokens');
  }, [searchParams]);
  // Any workspace may hold a code. Pool only decides whether that agent's
  // phones can be handed out to *other* workspaces, so it is a hint in the
  // create dialog, not a gate.
  const poolWorkspaces = useMemo(
    () => (workspaces.data?.items ?? []).filter((w) => w.kind === 'pool'),
    [workspaces.data]
  );
  const poolWorkspaceIds = useMemo(
    () => new Set(poolWorkspaces.map((w) => w.id)),
    [poolWorkspaces]
  );

  const params = useMemo(
    () => ({
      search: search || undefined,
      status: status === ALL ? undefined : status,
      workspaceId: scope.scopedWorkspaceId,
      offset,
      limit: ADMIN_PAGE_SIZE
    }),
    [offset, scope.scopedWorkspaceId, search, status]
  );
  const agents = useQuery({
    queryKey: ['admin-agents', params],
    queryFn: () => adminApi.listAgents(params),
    refetchInterval: pendingToggle ? TOGGLE_POLL_MS : 20_000
  });
  const tokens = useQuery({
    queryKey: ['admin-agent-tokens', scope.scopedWorkspaceId],
    queryFn: () => adminApi.listAgentTokens(scope.scopedWorkspaceId)
  });

  const updateMutation = useMutation({
    mutationFn: ({
      relayId,
      body
    }: {
      relayId: string;
      body: AdminAgentUpdate;
    }) => adminApi.updateAgent(relayId, body),
    onSuccess: () => {
      setEditAgent(null);
      toast.success(t('toast.updated'));
      void qc.invalidateQueries({ queryKey: ['admin-agents'] });
      void qc.invalidateQueries({ queryKey: ['admin-summary'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const lifecycleMutation = useMutation({
    mutationFn: async ({
      relayId,
      action
    }: {
      relayId: string;
      action: 'enable' | 'disable' | 'delete';
    }) => {
      if (action === 'enable')
        return { action, agent: await adminApi.enableAgent(relayId) };
      if (action === 'disable')
        return { action, agent: await adminApi.disableAgent(relayId) };
      await adminApi.deleteAgent(relayId);
      return { action, agent: null };
    },
    onSuccess: ({ action, agent }) => {
      setDeleteAgent(null);
      void qc.invalidateQueries({ queryKey: ['admin-agents'] });
      void qc.invalidateQueries({ queryKey: ['admin-summary'] });
      if (action === 'delete' || !agent) {
        toast.success(t('toast.updated'));
        return;
      }
      const wanted = action === 'enable';
      if (agent.connected === wanted) {
        toast.success(wanted ? t('toast.enabled') : t('toast.disabled'));
        return;
      }
      setPendingToggle({
        relayId: agent.relay_id,
        action,
        startedAt: Date.now()
      });
      toast.info(wanted ? t('toast.enableWaiting') : t('toast.disableWaiting'));
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const bulkDeleteMutation = useMutation({
    mutationFn: async (relayIds: string[]) => {
      for (const relayId of relayIds) {
        await adminApi.deleteAgent(relayId);
      }
      return relayIds.length;
    },
    onSuccess: (count) => {
      setBulkDeleteOpen(false);
      setSelectedAgentIds(new Set());
      toast.success(t('toast.bulkDeleted', { count }));
      void qc.invalidateQueries({ queryKey: ['admin-agents'] });
      void qc.invalidateQueries({ queryKey: ['admin-summary'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const createTokenMutation = useMutation({
    mutationFn: adminApi.createAgentToken,
    onSuccess: (token) => {
      setSecret(token.token);
      setCreateOpen(false);
      toast.success(t('toast.activationCreated'));
      void qc.invalidateQueries({ queryKey: ['admin-agent-tokens'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const revokeTokenMutation = useMutation({
    mutationFn: adminApi.revokeAgentToken,
    onSuccess: () => {
      toast.success(t('toast.activationRevoked'));
      void qc.invalidateQueries({ queryKey: ['admin-agent-tokens'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const replaceTokenMutation = useMutation({
    mutationFn: adminApi.replaceAgentToken,
    onSuccess: (token) => {
      setSecret(token.token);
      toast.success(t('toast.activationReplaced'));
      void qc.invalidateQueries({ queryKey: ['admin-agent-tokens'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const agentItems = useMemo(() => agents.data?.items ?? [], [agents.data]);
  const poolAgentCount = agentItems.filter(
    (agent) => agent.workspaceKind === 'pool'
  ).length;
  const workspaceAgentCount = agentItems.filter(
    (agent) => agent.workspaceKind !== 'pool'
  ).length;
  const visibleAgents = useMemo(
    () =>
      agentItems.filter((agent) =>
        agentGroup === 'pool'
          ? agent.workspaceKind === 'pool'
          : agent.workspaceKind !== 'pool'
      ),
    [agentGroup, agentItems]
  );

  useEffect(() => {
    setSelectedAgentIds(new Set());
  }, [agentGroup]);

  useEffect(() => {
    if (!pendingToggle) return;
    const wanted = pendingToggle.action === 'enable';
    const agent = visibleAgents.find(
      (item) => item.relay_id === pendingToggle.relayId
    );
    // A deleted or filtered-out agent counts as "no longer connected".
    const connected = agent?.connected ?? false;
    if (connected === wanted) {
      setPendingToggle(null);
      toast.success(wanted ? t('toast.enabled') : t('toast.disabled'));
      return;
    }
    if (Date.now() - pendingToggle.startedAt >= TOGGLE_WAIT_TIMEOUT_MS) {
      setPendingToggle(null);
      toast.warning(
        wanted ? t('toast.enableTimeout') : t('toast.disableTimeout')
      );
    }
  }, [pendingToggle, t, visibleAgents]);
  const selectedVisibleCount = visibleAgents.filter((agent) =>
    selectedAgentIds.has(agent.relay_id)
  ).length;
  const allVisibleSelected =
    visibleAgents.length > 0 && selectedVisibleCount === visibleAgents.length;
  const someVisibleSelected =
    selectedVisibleCount > 0 && selectedVisibleCount < visibleAgents.length;
  const selectedCount = selectedAgentIds.size;
  const lifecycleBusy =
    lifecycleMutation.isPending || bulkDeleteMutation.isPending;

  useEffect(() => {
    setSelectedAgentIds(new Set());
  }, [scope.scopedWorkspaceId, search, status, offset]);

  const toggleAgent = (relayId: string) => {
    setSelectedAgentIds((prev) => {
      const next = new Set(prev);
      if (next.has(relayId)) next.delete(relayId);
      else next.add(relayId);
      return next;
    });
  };

  const toggleVisibleAgents = () => {
    setSelectedAgentIds((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) {
        for (const agent of visibleAgents) next.delete(agent.relay_id);
      } else {
        for (const agent of visibleAgents) next.add(agent.relay_id);
      }
      return next;
    });
  };

  return (
    <div className='min-h-full bg-muted/20'>
      <AdminPageHeader
        title={t('title')}
        description={t('description')}
        action={
          activeTab === 'tokens' ? (
            <Button onClick={() => setCreateOpen(true)} className='h-9'>
              <Plus className='mr-2 size-4' />
              {t('newActivation')}
            </Button>
          ) : null
        }
      />
      <div className='space-y-3 p-3 md:p-4'>
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <div className='flex flex-col gap-3 rounded-md border bg-background p-3 lg:flex-row lg:items-center lg:justify-between'>
            <TabsList>
              <TabsTrigger value='agents'>{t('tabs.agents')}</TabsTrigger>
              <TabsTrigger value='tokens'>
                {t('tabs.activationCodes')}
              </TabsTrigger>
            </TabsList>
            <AdminWorkspaceScopeSelect
              value={scope.workspaceId}
              onChange={(value) => {
                scope.setWorkspaceId(value);
                setOffset(0);
              }}
              workspaces={scope.workspaces}
              allowGlobalScope={scope.allowGlobalScope}
              workspaceLabel={t('filters.workspace')}
              allWorkspacesLabel={t('filters.allWorkspaces')}
            />
          </div>

          <TabsContent value='agents' className='space-y-3'>
            <div className='space-y-3 rounded-md border bg-background p-3'>
              <div className='grid gap-2 md:grid-cols-2'>
                {(['pool', 'workspace'] as const).map((group) => {
                  const active = agentGroup === group;
                  const count =
                    group === 'pool' ? poolAgentCount : workspaceAgentCount;
                  return (
                    <button
                      key={group}
                      type='button'
                      className={`rounded-md border px-3 py-2 text-left ${
                        active ? 'border-primary bg-primary/5' : 'bg-muted/20'
                      }`}
                      onClick={() => {
                        setAgentGroup(group);
                        setOffset(0);
                      }}
                    >
                      <span className='flex items-center justify-between gap-3 text-sm font-medium'>
                        <span>{t(`agentGroups.${group}.title`)}</span>
                        <span className='rounded-full bg-background px-2 py-0.5 text-xs text-muted-foreground'>
                          {count}
                        </span>
                      </span>
                      <span className='mt-1 block text-xs text-muted-foreground'>
                        {t(`agentGroups.${group}.description`)}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className='grid gap-2 lg:grid-cols-[minmax(260px,1fr)_190px]'>
                <SearchField
                  value={search}
                  onChange={(value) => {
                    setSearch(value);
                    setOffset(0);
                  }}
                  placeholder={t('searchPlaceholder')}
                />
                <Select
                  value={status}
                  onValueChange={(value) => {
                    setStatus(value);
                    setOffset(0);
                  }}
                >
                  <SelectTrigger className='w-full lg:w-[170px]'>
                    <SelectValue placeholder={t('filters.status')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>
                      {t('filters.allStatuses')}
                    </SelectItem>
                    <SelectItem value='online'>
                      {t('statuses.online')}
                    </SelectItem>
                    <SelectItem value='offline'>
                      {t('statuses.offline')}
                    </SelectItem>
                    <SelectItem value='disabled'>
                      {t('statuses.disabled')}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {agents.isError ? (
              <AdminErrorState
                message={formatAdminApiError(agents.error)}
                onRetry={() => void agents.refetch()}
              />
            ) : null}

            <div className='overflow-hidden rounded-md border bg-background'>
              {selectedCount > 0 ? (
                <div className='flex flex-col gap-2 border-b bg-muted/30 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between'>
                  <span className='font-medium'>
                    {t('bulk.selected', { count: selectedCount })}
                  </span>
                  <div className='flex gap-2'>
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      onClick={() => setSelectedAgentIds(new Set())}
                    >
                      {t('bulk.clear')}
                    </Button>
                    <Button
                      type='button'
                      variant='destructive'
                      size='sm'
                      disabled={lifecycleBusy}
                      onClick={() => setBulkDeleteOpen(true)}
                    >
                      {t('bulk.delete')}
                    </Button>
                  </div>
                </div>
              ) : null}
              <div className='overflow-x-auto'>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className='w-[44px]'>
                        <Checkbox
                          checked={
                            allVisibleSelected
                              ? true
                              : someVisibleSelected
                                ? 'indeterminate'
                                : false
                          }
                          disabled={visibleAgents.length === 0 || lifecycleBusy}
                          aria-label={t('bulk.selectVisible')}
                          onCheckedChange={toggleVisibleAgents}
                        />
                      </TableHead>
                      <TableHead>{t('table.agent')}</TableHead>
                      <TableHead>{t('table.workspace')}</TableHead>
                      <TableHead>{t('table.health')}</TableHead>
                      <TableHead>{t('table.lastSeen')}</TableHead>
                      <TableHead>{t('table.version')}</TableHead>
                      <TableHead>{t('table.devices')}</TableHead>
                      <TableHead className='w-[360px] text-right'>
                        {t('table.actions')}
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {agents.isLoading ? (
                      <AdminTableSkeleton columns={8} />
                    ) : null}
                    {visibleAgents.map((agent) => (
                      <TableRow
                        key={agent.relay_id}
                        data-state={
                          selectedAgentIds.has(agent.relay_id)
                            ? 'selected'
                            : undefined
                        }
                      >
                        <TableCell>
                          <Checkbox
                            checked={selectedAgentIds.has(agent.relay_id)}
                            disabled={lifecycleBusy}
                            aria-label={t('bulk.selectAgent', {
                              agent: agent.name || agent.relay_id
                            })}
                            onCheckedChange={() => toggleAgent(agent.relay_id)}
                          />
                        </TableCell>
                        <TableCell className='py-2'>
                          <div className='min-w-[180px]'>
                            <p className='font-medium'>
                              {agent.name || agent.relay_id}
                            </p>
                            <p className='text-xs text-muted-foreground'>
                              {[agent.hostname, agent.ip]
                                .filter(Boolean)
                                .join(' · ') || agent.relay_id}
                            </p>
                          </div>
                        </TableCell>
                        <TableCell className='py-2'>
                          {agent.workspaceName || agent.workspaceId}
                        </TableCell>
                        <TableCell className='py-2'>
                          <StatusBadge value={agent.health} />
                        </TableCell>
                        <TableCell className='py-2 text-sm text-muted-foreground'>
                          {dateLabel(agent.last_heartbeat_at)}
                        </TableCell>
                        <TableCell className='py-2'>
                          {agent.version || '-'}
                        </TableCell>
                        <TableCell className='py-2'>
                          <AgentPhonesSummary
                            agent={agent}
                            onView={() => setViewPhonesAgent(agent)}
                          />
                        </TableCell>
                        <TableCell className='py-2'>
                          <div className='flex flex-nowrap justify-end gap-1'>
                            {PHONE_ALLOCATION_ENABLED &&
                            agentGroup === 'pool' ? (
                              <PhoneAllocationAction
                                agent={agent}
                                onOpen={() => setPhoneAgent(agent)}
                              />
                            ) : null}
                            <Button
                              size='sm'
                              variant='ghost'
                              className='h-8 px-2.5'
                              onClick={() => setEditAgent(agent)}
                            >
                              <Pencil className='mr-1.5 size-3.5' />
                              {t('actions.edit')}
                            </Button>
                            <Button
                              size='sm'
                              variant='ghost'
                              className='h-8 px-2.5'
                              disabled={
                                lifecycleBusy ||
                                pendingToggle?.relayId === agent.relay_id
                              }
                              onClick={() =>
                                lifecycleMutation.mutate({
                                  relayId: agent.relay_id,
                                  action:
                                    agent.status === 'disabled'
                                      ? 'enable'
                                      : 'disable'
                                })
                              }
                            >
                              {pendingToggle?.relayId === agent.relay_id ? (
                                <SubmitSpinner />
                              ) : (
                                <Power className='mr-1.5 size-3.5' />
                              )}
                              {pendingToggle?.relayId === agent.relay_id
                                ? pendingToggle.action === 'enable'
                                  ? t('actions.enableWaiting')
                                  : t('actions.disableWaiting')
                                : agent.status === 'disabled'
                                  ? t('actions.enable')
                                  : t('actions.disable')}
                            </Button>
                            <Button
                              size='sm'
                              variant='ghost'
                              className='h-8 px-2.5 text-destructive hover:text-destructive'
                              onClick={() => setDeleteAgent(agent)}
                            >
                              <Trash2 className='mr-1.5 size-3.5' />
                              {t('actions.delete')}
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                    {!agents.isLoading && visibleAgents.length === 0 ? (
                      <TableRow>
                        <TableCell
                          colSpan={8}
                          className='h-28 text-center text-sm text-muted-foreground'
                        >
                          {t(`agentGroups.${agentGroup}.empty`)}
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </TableBody>
                </Table>
              </div>
              <AdminPagination
                offset={offset}
                limit={ADMIN_PAGE_SIZE}
                total={visibleAgents.length}
                onOffsetChange={setOffset}
              />
            </div>
          </TabsContent>

          <TabsContent value='tokens'>
            <section className='overflow-hidden rounded-md border bg-background'>
              <div className='border-b px-4 py-3'>
                <h2 className='text-sm font-semibold'>
                  {t('activationCodes.title')}
                </h2>
              </div>
              <div className='overflow-x-auto'>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('activationCodes.name')}</TableHead>
                      <TableHead>{t('activationCodes.workspace')}</TableHead>
                      <TableHead>{t('activationCodes.prefix')}</TableHead>
                      <TableHead>{t('activationCodes.status')}</TableHead>
                      <TableHead>{t('activationCodes.created')}</TableHead>
                      <TableHead className='w-[220px] text-right'>
                        {t('table.actions')}
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tokens.data?.map((token) => (
                      <TableRow key={token.id}>
                        <TableCell>{token.name || '-'}</TableCell>
                        <TableCell>
                          {token.workspaceName || token.workspaceId}
                        </TableCell>
                        <TableCell>
                          <code className='rounded bg-muted px-1.5 py-0.5 text-xs'>
                            {token.prefix}
                          </code>
                        </TableCell>
                        <TableCell>
                          <StatusBadge value={token.status} />
                        </TableCell>
                        <TableCell className='text-sm text-muted-foreground'>
                          {dateLabel(token.created_at)}
                        </TableCell>
                        <TableCell className='text-right'>
                          <div className='flex justify-end gap-1'>
                            {token.status === 'active' ? (
                              <>
                                <Button
                                  size='sm'
                                  variant='outline'
                                  disabled={replaceTokenMutation.isPending}
                                  onClick={() =>
                                    replaceTokenMutation.mutate(token.id)
                                  }
                                >
                                  <RefreshCw className='mr-1.5 size-3.5' />
                                  {t('activationCodes.getNewCode')}
                                </Button>
                                <Button
                                  size='sm'
                                  variant='ghost'
                                  className='text-destructive hover:text-destructive'
                                  disabled={revokeTokenMutation.isPending}
                                  onClick={() =>
                                    revokeTokenMutation.mutate(token.id)
                                  }
                                >
                                  {t('activationCodes.revoke')}
                                </Button>
                              </>
                            ) : null}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                    {!tokens.isLoading && (tokens.data ?? []).length === 0 ? (
                      <TableRow>
                        <TableCell
                          colSpan={6}
                          className='h-20 text-center text-sm text-muted-foreground'
                        >
                          {t('activationCodes.empty')}
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </TableBody>
                </Table>
              </div>
            </section>
          </TabsContent>
        </Tabs>
      </div>

      <AgentActivationDialog
        open={createOpen}
        pending={createTokenMutation.isPending}
        workspaces={workspaces.data?.items ?? []}
        poolWorkspaceIds={poolWorkspaceIds}
        selectedWorkspaceId={
          scope.scopedWorkspaceId ??
          poolWorkspaces[0]?.id ??
          workspaces.data?.items[0]?.id ??
          ''
        }
        onClose={() => setCreateOpen(false)}
        onSubmit={(body) => createTokenMutation.mutate(body)}
      />
      <AgentEditDialog
        agent={editAgent}
        workspaces={workspaces.data?.items ?? []}
        pending={updateMutation.isPending}
        onClose={() => setEditAgent(null)}
        onSubmit={(relayId, body) => updateMutation.mutate({ relayId, body })}
      />
      <AgentPhoneAllocationDialog
        agent={phoneAgent}
        onClose={() => setPhoneAgent(null)}
      />
      <AgentPhonesViewDialog
        agent={viewPhonesAgent}
        onClose={() => setViewPhonesAgent(null)}
      />
      <AlertDialog
        open={!!deleteAgent}
        onOpenChange={(open) => !open && setDeleteAgent(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('delete.title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('delete.description')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className='bg-destructive text-destructive-foreground hover:bg-destructive/90'
              onClick={() =>
                deleteAgent &&
                lifecycleMutation.mutate({
                  relayId: deleteAgent.relay_id,
                  action: 'delete'
                })
              }
            >
              {t('delete.confirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog
        open={bulkDeleteOpen}
        onOpenChange={(open) => !open && setBulkDeleteOpen(false)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('bulk.deleteTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('bulk.deleteDescription', { count: selectedCount })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={bulkDeleteMutation.isPending}>
              {t('common.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              className='bg-destructive text-destructive-foreground hover:bg-destructive/90'
              disabled={bulkDeleteMutation.isPending || selectedCount === 0}
              onClick={() =>
                bulkDeleteMutation.mutate(Array.from(selectedAgentIds))
              }
            >
              {bulkDeleteMutation.isPending ? <SubmitSpinner /> : null}
              {t('bulk.deleteConfirm', { count: selectedCount })}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <SecretDialog
        open={!!secret}
        title={t('secret.title')}
        description={t('secret.description')}
        secret={secret}
        onClose={() => setSecret(null)}
      />
    </div>
  );
}

const PHONE_VIEW_PAGE_SIZE = 10;

function AgentPhonesViewDialog({
  agent,
  onClose
}: {
  agent: AdminAgentOut | null;
  onClose: () => void;
}) {
  const t = useTranslations('adminConsole.agents.phoneViewer');
  const [phoneSearch, setPhoneSearch] = useState('');
  const [phoneOffset, setPhoneOffset] = useState(0);

  useEffect(() => {
    setPhoneSearch('');
    setPhoneOffset(0);
  }, [agent?.relay_id]);

  useEffect(() => {
    setPhoneOffset(0);
  }, [phoneSearch]);

  const phoneParams = useMemo(
    () => ({
      search: phoneSearch || undefined,
      offset: phoneOffset,
      limit: PHONE_VIEW_PAGE_SIZE
    }),
    [phoneOffset, phoneSearch]
  );

  const phones = useQuery({
    queryKey: ['admin-agent-phones-view', agent?.relay_id, phoneParams],
    queryFn: () => adminApi.listAgentPhones(agent?.relay_id || '', phoneParams),
    enabled: !!agent
  });

  const displayedPhones = phones.data?.items ?? [];

  return (
    <Dialog open={!!agent} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className='flex h-[min(640px,calc(100vh-2rem))] w-[calc(100vw-2rem)] !max-w-[920px] flex-col gap-0 overflow-hidden p-0'>
        <DialogHeader className='border-b px-5 py-4'>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        {agent ? (
          <div className='flex min-h-0 flex-1 flex-col'>
            <div className='grid gap-2 border-b bg-muted/30 px-5 py-3 md:grid-cols-3'>
              <div className='min-w-0'>
                <p className='text-xs font-medium text-muted-foreground'>
                  {t('agent')}
                </p>
                <p className='truncate font-medium'>
                  {agent.name || agent.relay_id}
                </p>
              </div>
              <div className='min-w-0'>
                <p className='text-xs font-medium text-muted-foreground'>
                  {t('managedBy')}
                </p>
                <p className='truncate font-medium'>
                  {agent.workspaceName || agent.workspaceId}
                </p>
              </div>
              <div className='min-w-0'>
                <p className='text-xs font-medium text-muted-foreground'>
                  {t('phones')}
                </p>
                <p className='font-medium'>
                  {phones.data?.total ?? agent.deviceCount}
                </p>
              </div>
            </div>

            <div className='border-b p-3'>
              <SearchField
                value={phoneSearch}
                onChange={setPhoneSearch}
                placeholder={t('searchPlaceholder')}
              />
            </div>

            {phones.isError ? (
              <div className='p-4'>
                <AdminErrorState
                  message={formatAdminApiError(phones.error)}
                  onRetry={() => void phones.refetch()}
                />
              </div>
            ) : null}

            <div className='min-h-0 flex-1 overflow-auto p-3'>
              <div className='overflow-hidden rounded-md border'>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('table.phone')}</TableHead>
                      <TableHead>{t('table.status')}</TableHead>
                      <TableHead>{t('table.assignedTo')}</TableHead>
                      <TableHead>{t('table.lastSeen')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {phones.isLoading ? (
                      <AdminTableSkeleton columns={4} />
                    ) : null}
                    {displayedPhones.map((phone) => (
                      <AgentPhoneViewRow key={phone.serial} phone={phone} />
                    ))}
                    {!phones.isLoading && displayedPhones.length === 0 ? (
                      <TableRow>
                        <TableCell
                          colSpan={4}
                          className='h-24 text-center text-sm text-muted-foreground'
                        >
                          {t('empty')}
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </TableBody>
                </Table>
                <AdminPagination
                  offset={phones.data?.offset ?? phoneOffset}
                  limit={phones.data?.limit ?? PHONE_VIEW_PAGE_SIZE}
                  total={phones.data?.total ?? 0}
                  onOffsetChange={setPhoneOffset}
                />
              </div>
            </div>

            <DialogFooter className='border-t p-3'>
              <Button
                type='button'
                variant='outline'
                className='h-9'
                onClick={onClose}
              >
                {t('close')}
              </Button>
            </DialogFooter>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function AgentActivationDialog({
  open,
  pending,
  workspaces,
  poolWorkspaceIds,
  selectedWorkspaceId,
  onClose,
  onSubmit
}: {
  open: boolean;
  pending: boolean;
  workspaces: Array<{ id: string; businessName: string }>;
  poolWorkspaceIds: Set<string>;
  selectedWorkspaceId: string;
  onClose: () => void;
  onSubmit: (body: { workspaceId: string; name?: string }) => void;
}) {
  const t = useTranslations('adminConsole.agents.activationDialog');
  const tCommon = useTranslations('adminConsole.agents.common');
  const [workspaceId, setWorkspaceId] = useState(selectedWorkspaceId);
  const [name, setName] = useState('');
  useEffect(() => {
    if (open) setWorkspaceId(selectedWorkspaceId);
  }, [open, selectedWorkspaceId]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit({ workspaceId, name });
  };
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <form className='space-y-4' onSubmit={submit}>
          <div>
            <Label className='mb-2 block'>{t('workspace')}</Label>
            <Select required value={workspaceId} onValueChange={setWorkspaceId}>
              <SelectTrigger className='w-full'>
                <SelectValue placeholder={t('selectWorkspace')} />
              </SelectTrigger>
              <SelectContent>
                {workspaces.map((workspace) => (
                  <SelectItem key={workspace.id} value={workspace.id}>
                    {workspace.businessName}
                    {poolWorkspaceIds.has(workspace.id)
                      ? ` — ${t('poolSuffix')}`
                      : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className='mt-2 text-xs text-muted-foreground'>
              {poolWorkspaceIds.has(workspaceId)
                ? t('poolHint')
                : t('tenantHint')}
            </p>
          </div>
          <div>
            <Label className='mb-2 block'>{t('name')}</Label>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t('namePlaceholder')}
            />
          </div>
          <DialogFooter>
            <Button type='button' variant='outline' onClick={onClose}>
              {tCommon('cancel')}
            </Button>
            <Button type='submit' disabled={pending || !workspaceId}>
              {pending ? <SubmitSpinner /> : null}
              {tCommon('create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AgentEditDialog({
  agent,
  workspaces,
  pending,
  onClose,
  onSubmit
}: {
  agent: AdminAgentOut | null;
  workspaces: Array<{ id: string; businessName: string }>;
  pending: boolean;
  onClose: () => void;
  onSubmit: (relayId: string, body: AdminAgentUpdate) => void;
}) {
  const t = useTranslations('adminConsole.agents.editDialog');
  const tCommon = useTranslations('adminConsole.agents.common');
  const [draft, setDraft] = useState<AdminAgentUpdate>({});
  useEffect(() => {
    setDraft({});
  }, [agent?.relay_id]);
  const active = agent
    ? {
        name: draft.name ?? agent.name,
        status: draft.status ?? agent.status,
        workspaceId: draft.workspaceId ?? agent.workspaceId
      }
    : null;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (agent && active) onSubmit(agent.relay_id, active);
  };
  return (
    <Dialog open={!!agent} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        {active ? (
          <form className='space-y-4' onSubmit={submit}>
            <div>
              <Label className='mb-2 block'>{t('name')}</Label>
              <Input
                value={active.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </div>
            <div>
              <Label className='mb-2 block'>{t('workspace')}</Label>
              {/* The activation code owns this value; PATCH rejects any other
                  one with AGENT_WORKSPACE_IS_IMMUTABLE. */}
              <Select disabled value={active.workspaceId}>
                <SelectTrigger className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {workspaces.map((workspace) => (
                    <SelectItem key={workspace.id} value={workspace.id}>
                      {workspace.businessName}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className='mt-2 text-xs text-muted-foreground'>
                {t('workspaceImmutableHint')}
              </p>
            </div>
            <div>
              <Label className='mb-2 block'>{t('status')}</Label>
              <Select
                value={active.status}
                onValueChange={(value) => setDraft({ ...draft, status: value })}
              >
                <SelectTrigger className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value='online'>{t('online')}</SelectItem>
                  <SelectItem value='offline'>{t('offline')}</SelectItem>
                  <SelectItem value='disabled'>{t('disabled')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button type='button' variant='outline' onClick={onClose}>
                {tCommon('cancel')}
              </Button>
              <Button type='submit' disabled={pending}>
                {pending ? <SubmitSpinner /> : null}
                {tCommon('save')}
              </Button>
            </DialogFooter>
          </form>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function AgentPhoneAllocationDialog({
  agent,
  onClose
}: {
  agent: AdminAgentOut | null;
  onClose: () => void;
}) {
  const t = useTranslations('adminConsole.agents.phoneAllocation');
  const tCommon = useTranslations('adminConsole.agents.common');
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [targetWorkspaceId, setTargetWorkspaceId] = useState('');
  const [filter, setFilter] = useState(ALL);
  const [phoneSearch, setPhoneSearch] = useState('');
  const [phoneOffset, setPhoneOffset] = useState(0);
  const [workspaceSearch, setWorkspaceSearch] = useState('');
  const [allocationStep, setAllocationStep] = useState<'phones' | 'workspace'>(
    'phones'
  );

  useEffect(() => {
    setSelected(new Set());
    setTargetWorkspaceId('');
    setFilter(ALL);
    setPhoneSearch('');
    setPhoneOffset(0);
    setWorkspaceSearch('');
    setAllocationStep('phones');
  }, [agent?.relay_id]);

  useEffect(() => {
    setPhoneOffset(0);
  }, [filter, phoneSearch]);

  const phoneParams = useMemo(
    () => ({
      search: phoneSearch || undefined,
      assignedWorkspaceId:
        filter === ALL
          ? undefined
          : filter === UNASSIGNED_PHONE_FILTER
            ? UNASSIGNED_PHONE_FILTER
            : filter,
      offset: phoneOffset,
      limit: PHONE_PAGE_SIZE
    }),
    [filter, phoneOffset, phoneSearch]
  );

  const phones = useQuery({
    queryKey: ['admin-agent-phones', agent?.relay_id, phoneParams],
    queryFn: () => adminApi.listAgentPhones(agent?.relay_id || '', phoneParams),
    enabled: !!agent
  });

  const assignableWorkspaces = useQuery({
    queryKey: [
      'admin-workspaces-assignable',
      {
        search: workspaceSearch || undefined,
        offset: 0,
        limit: WORKSPACE_SEARCH_LIMIT
      }
    ],
    queryFn: () =>
      adminApi.listAssignableWorkspaces({
        search: workspaceSearch || undefined,
        offset: 0,
        limit: WORKSPACE_SEARCH_LIMIT
      }),
    enabled: !!agent
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['admin-agent-phones'] });
    void qc.invalidateQueries({ queryKey: ['admin-agents'] });
    void qc.invalidateQueries({ queryKey: ['admin-devices'] });
    void qc.invalidateQueries({ queryKey: ['admin-summary'] });
  };

  // The pool rule and the missing-device case need the workspace name and the
  // way out; everything else keeps the shared formatter.
  const phoneErrorMessage = (error: unknown) => {
    const code = adminApiErrorCode(error);
    if (code === 'AGENT_NOT_IN_POOL_WORKSPACE') {
      return t('tenantLocked', {
        workspace: agent?.workspaceName || agent?.workspaceId || '-'
      });
    }
    if (code === 'DEVICE_NOT_FOUND') return t('deviceNotFound');
    return formatAdminApiError(error);
  };

  const assignMutation = useMutation({
    mutationFn: () =>
      adminApi.assignAgentPhones(agent?.relay_id || '', {
        targetWorkspaceId,
        serials: Array.from(selected)
      }),
    onSuccess: () => {
      setSelected(new Set());
      setTargetWorkspaceId('');
      setWorkspaceSearch('');
      setAllocationStep('phones');
      toast.success(t('toast.assigned'));
      invalidate();
    },
    onError: (error) => toast.error(phoneErrorMessage(error))
  });

  const unassignMutation = useMutation({
    mutationFn: () =>
      adminApi.unassignAgentPhones(agent?.relay_id || '', {
        serials: Array.from(selected)
      }),
    onSuccess: () => {
      setSelected(new Set());
      toast.success(t('toast.returned'));
      invalidate();
    },
    onError: (error) => toast.error(phoneErrorMessage(error))
  });

  const displayedPhones = phones.data?.items ?? [];
  const assignableWorkspaceItems = assignableWorkspaces.data?.items ?? [];
  const busy = assignMutation.isPending || unassignMutation.isPending;
  const selectedCount = selected.size;
  const targetWorkspaceName = assignableWorkspaceItems.find(
    (workspace) => workspace.id === targetWorkspaceId
  )?.businessName;
  const assignLabel = targetWorkspaceId
    ? t('assignToWorkspace', {
        count: selectedCount,
        workspace: targetWorkspaceName || targetWorkspaceId
      })
    : t('chooseTargetWorkspace');
  const selectedSerials = Array.from(selected);

  const toggleSerial = (serial: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(serial)) next.delete(serial);
      else next.add(serial);
      return next;
    });
  };

  const selectDisplayed = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const phone of displayedPhones) next.add(phone.serial);
      return next;
    });
  };

  return (
    <Dialog open={!!agent} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className='flex h-[min(760px,calc(100vh-2rem))] w-[calc(100vw-2rem)] !max-w-[1180px] flex-col gap-0 overflow-hidden p-0'>
        <DialogHeader className='border-b px-5 py-4'>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        {agent ? (
          <div className='flex min-h-0 flex-1 flex-col'>
            <div className='grid gap-2 border-b bg-muted/30 px-5 py-3 md:grid-cols-3'>
              <div className='min-w-0'>
                <p className='text-xs font-medium text-muted-foreground'>
                  {t('agent')}
                </p>
                <p className='truncate font-medium'>
                  {agent.name || agent.relay_id}
                </p>
              </div>
              <div className='min-w-0'>
                <p className='text-xs font-medium text-muted-foreground'>
                  {t('managedBy')}
                </p>
                <p className='truncate font-medium'>
                  {agent.workspaceName || agent.workspaceId}
                </p>
              </div>
              <div className='min-w-0'>
                <p className='text-xs font-medium text-muted-foreground'>
                  {t('phones')}
                </p>
                <p className='font-medium'>
                  {phones.data?.total ?? agent.serials.length}
                </p>
              </div>
            </div>

            <div className='border-b p-3'>
              <Tabs
                value={allocationStep}
                onValueChange={(step) =>
                  setAllocationStep(step as 'phones' | 'workspace')
                }
              >
                <TabsList className='w-full'>
                  <TabsTrigger value='phones'>
                    <StepNumber>1</StepNumber>
                    {t('steps.phones.title')}
                    {selectedCount > 0 ? (
                      <Badge variant='secondary'>{selectedCount}</Badge>
                    ) : null}
                  </TabsTrigger>
                  <TabsTrigger value='workspace' disabled={selectedCount === 0}>
                    <StepNumber>2</StepNumber>
                    {t('steps.workspace.title')}
                  </TabsTrigger>
                </TabsList>
              </Tabs>
              <p className='mt-2 text-xs text-muted-foreground'>
                {allocationStep === 'phones'
                  ? t('steps.phones.description')
                  : t('steps.workspace.description')}
              </p>
            </div>

            {allocationStep === 'phones' ? (
              <>
                <div className='grid gap-2 border-b p-3 sm:grid-cols-[minmax(220px,1fr)_170px_auto]'>
                  <SearchField
                    value={phoneSearch}
                    onChange={setPhoneSearch}
                    placeholder={t('searchPlaceholder')}
                  />
                  <Select value={filter} onValueChange={setFilter}>
                    <SelectTrigger className='w-full'>
                      <SelectValue placeholder={t('filter')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ALL}>{t('allPhones')}</SelectItem>
                      <SelectItem value={UNASSIGNED_PHONE_FILTER}>
                        {t('poolPhones')}
                      </SelectItem>
                      {assignableWorkspaceItems.map((workspace) => (
                        <SelectItem key={workspace.id} value={workspace.id}>
                          {workspace.businessName}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    type='button'
                    variant='outline'
                    className='h-10 whitespace-nowrap px-3'
                    disabled={displayedPhones.length === 0}
                    onClick={selectDisplayed}
                  >
                    {t('selectVisible')}
                  </Button>
                </div>

                {phones.isError ? (
                  <div className='p-4'>
                    <AdminErrorState
                      message={formatAdminApiError(phones.error)}
                      onRetry={() => void phones.refetch()}
                    />
                  </div>
                ) : null}

                <div className='min-h-0 flex-1 overflow-auto p-3'>
                  <div className='overflow-hidden rounded-md border'>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className='w-[42px]' />
                          <TableHead>{t('table.phone')}</TableHead>
                          <TableHead>{t('table.status')}</TableHead>
                          <TableHead>{t('table.assignedTo')}</TableHead>
                          <TableHead>{t('table.lastSeen')}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {phones.isLoading ? (
                          <AdminTableSkeleton columns={5} />
                        ) : null}
                        {displayedPhones.map((phone) => (
                          <AgentPhoneRow
                            key={phone.serial}
                            phone={phone}
                            checked={selected.has(phone.serial)}
                            onToggle={() => toggleSerial(phone.serial)}
                          />
                        ))}
                        {!phones.isLoading && displayedPhones.length === 0 ? (
                          <TableRow>
                            <TableCell
                              colSpan={5}
                              className='h-24 text-center text-sm text-muted-foreground'
                            >
                              {t('empty')}
                            </TableCell>
                          </TableRow>
                        ) : null}
                      </TableBody>
                    </Table>
                    {phones.data && phones.data.total > phones.data.limit ? (
                      <AdminPagination
                        offset={phones.data.offset}
                        limit={phones.data.limit}
                        total={phones.data.total}
                        onOffsetChange={setPhoneOffset}
                      />
                    ) : null}
                  </div>
                </div>
              </>
            ) : (
              <div className='min-h-0 flex-1 overflow-auto p-3'>
                <div className='grid gap-3 lg:grid-cols-[minmax(0,1fr)_320px]'>
                  <Card className='gap-3 py-4'>
                    <CardHeader className='px-4'>
                      <CardTitle className='text-base'>
                        {t('targetWorkspaceLabel')}
                      </CardTitle>
                      <CardDescription>
                        {t('targetWorkspaceHelp')}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className='px-4'>
                      {/* Server-side search: cmdk must not re-filter the page it gets. */}
                      <Command shouldFilter={false} className='border'>
                        <CommandInput
                          value={workspaceSearch}
                          onValueChange={setWorkspaceSearch}
                          placeholder={t('workspaceSearchPlaceholder')}
                        />
                        <CommandList>
                          <CommandEmpty>
                            {workspaceSearch
                              ? t('noTargetWorkspaces')
                              : t('noTargetWorkspacesHint')}
                          </CommandEmpty>
                          <CommandGroup>
                            {assignableWorkspaceItems.map((workspace) => (
                              <CommandItem
                                key={workspace.id}
                                value={workspace.id}
                                onSelect={() =>
                                  setTargetWorkspaceId(workspace.id)
                                }
                                className='gap-3'
                              >
                                <Check
                                  className={cn(
                                    workspace.id === targetWorkspaceId
                                      ? 'opacity-100'
                                      : 'opacity-0'
                                  )}
                                />
                                <span className='min-w-0'>
                                  <span className='block truncate text-sm font-medium'>
                                    {workspace.businessName}
                                  </span>
                                  <span className='block truncate text-xs text-muted-foreground'>
                                    {workspace.id}
                                  </span>
                                </span>
                              </CommandItem>
                            ))}
                          </CommandGroup>
                        </CommandList>
                      </Command>
                    </CardContent>
                  </Card>

                  <Card className='gap-3 py-4'>
                    <CardHeader className='px-4'>
                      <CardTitle className='text-base'>
                        {t('selectedPhonesTitle', { count: selectedCount })}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className='flex flex-wrap gap-1.5 px-4'>
                      {selectedSerials.slice(0, 12).map((serial) => (
                        <Badge
                          key={serial}
                          variant='secondary'
                          className='font-mono'
                        >
                          {serial}
                        </Badge>
                      ))}
                      {selectedSerials.length > 12 ? (
                        <Badge variant='outline'>
                          +{selectedSerials.length - 12}
                        </Badge>
                      ) : null}
                    </CardContent>
                  </Card>
                </div>
              </div>
            )}

            <DialogFooter className='border-t p-3 sm:justify-between'>
              {allocationStep === 'phones' ? (
                <Button
                  type='button'
                  variant='outline'
                  disabled={busy || selectedCount === 0}
                  onClick={() => unassignMutation.mutate()}
                >
                  {unassignMutation.isPending ? (
                    <SubmitSpinner />
                  ) : (
                    <RotateCcw />
                  )}
                  {t('returnToPool', { count: selectedCount })}
                </Button>
              ) : (
                <Button
                  type='button'
                  variant='outline'
                  onClick={() => setAllocationStep('phones')}
                >
                  <ArrowLeft />
                  {t('backToPhones')}
                </Button>
              )}
              <div className='flex gap-2'>
                <Button type='button' variant='ghost' onClick={onClose}>
                  {tCommon('cancel')}
                </Button>
                {allocationStep === 'phones' ? (
                  <Button
                    type='button'
                    disabled={selectedCount === 0}
                    onClick={() => setAllocationStep('workspace')}
                  >
                    {t('nextToWorkspace', { count: selectedCount })}
                    <ArrowRight />
                  </Button>
                ) : (
                  <Button
                    type='button'
                    disabled={busy || selectedCount === 0 || !targetWorkspaceId}
                    onClick={() => assignMutation.mutate()}
                  >
                    {assignMutation.isPending ? (
                      <SubmitSpinner />
                    ) : (
                      <ArrowRightLeft />
                    )}
                    {assignLabel}
                  </Button>
                )}
              </div>
            </DialogFooter>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

/**
 * `pooled` is the only field that separates "still in the owning workspace's
 * pool" from "handed out": both states used to render the same workspace name.
 */
function PhonePooledCell({ phone }: { phone: AdminAgentPhoneOut }) {
  if (phone.pooled) return <StatusBadge value='in_pool' />;
  return (
    <div className='flex flex-wrap items-center gap-1.5'>
      <StatusBadge value='allocated' />
      <span className='text-sm'>
        {phone.assignedWorkspaceName || phone.assignedWorkspaceId || '-'}
      </span>
    </div>
  );
}

function AgentPhoneViewRow({ phone }: { phone: AdminAgentPhoneOut }) {
  return (
    <TableRow>
      <TableCell>
        <div className='min-w-[180px]'>
          <p className='font-medium'>
            {phone.name || phone.model || phone.serial}
          </p>
          <p className='font-mono text-xs text-muted-foreground'>
            {phone.serial}
          </p>
        </div>
      </TableCell>
      <TableCell>
        <StatusBadge value={phone.state || phone.status} />
      </TableCell>
      <TableCell>
        <PhonePooledCell phone={phone} />
      </TableCell>
      <TableCell className='text-sm text-muted-foreground'>
        {dateLabel(phone.last_seen)}
      </TableCell>
    </TableRow>
  );
}

function AgentPhoneRow({
  phone,
  checked,
  onToggle
}: {
  phone: AdminAgentPhoneOut;
  checked: boolean;
  onToggle: () => void;
}) {
  const t = useTranslations('adminConsole.agents.phoneAllocation');
  return (
    <TableRow>
      <TableCell>
        <input
          type='checkbox'
          className='size-4'
          checked={checked}
          onChange={onToggle}
          aria-label={phone.serial}
        />
      </TableCell>
      <TableCell>
        <div className='min-w-[180px]'>
          <p className='font-medium'>
            {phone.name || phone.model || phone.serial}
          </p>
          <p className='font-mono text-xs text-muted-foreground'>
            {phone.serial}
          </p>
        </div>
      </TableCell>
      <TableCell>
        <div className='flex flex-wrap gap-1'>
          <StatusBadge value={phone.registered ? phone.status : 'ready'} />
          <StatusBadge value={phone.state} />
        </div>
      </TableCell>
      <TableCell>
        <div className='min-w-[180px] text-sm'>
          <PhonePooledCell phone={phone} />
          <p className='mt-1 text-xs text-muted-foreground'>
            {t('managedByValue', {
              workspace:
                phone.managedByWorkspaceName ||
                phone.managedByWorkspaceId ||
                '-'
            })}
          </p>
        </div>
      </TableCell>
      <TableCell className='text-sm text-muted-foreground'>
        {dateLabel(phone.last_seen)}
      </TableCell>
    </TableRow>
  );
}
