'use client';

import {
  type FormEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useState
} from 'react';
import {
  Edit,
  KeyRound,
  LogIn,
  Plus,
  Server,
  ShieldCheck,
  Smartphone,
  Trash2,
  UserCog,
  Users
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useSearchParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ROUTES } from '@/config/routes';
import { Link, useRouter } from '@/i18n/navigation';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { Textarea } from '@/components/ui/textarea';
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
import { useAdminWorkspaceScope } from '../hooks/use-admin-workspace-scope';
import type { ProtoOrganization } from '@/features/device-farm';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import {
  adminApi,
  type AdminUserCreate,
  type AdminUserOut,
  type AdminWorkspaceCreate,
  type AdminWorkspaceKind,
  type AdminWorkspaceOut,
  formatAdminApiError
} from '../services/admin-api';

const ALL = '__all__';
// Smaller than ADMIN_PAGE_SIZE so the phone table stays inside the dialog's max-h.
const DIALOG_DEVICE_PAGE_SIZE = 10;
type ResetPasswordTarget = Pick<AdminUserOut, 'user_id' | 'email' | 'name'>;

function dateLabel(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '-';
}

function workspaceToOrganization(
  workspace: AdminWorkspaceOut
): ProtoOrganization {
  return {
    id: workspace.id,
    businessName: workspace.businessName,
    businessEmail: workspace.businessEmail ?? null,
    businessLogo: workspace.businessLogo ?? null,
    slug: workspace.slug,
    status: workspace.status,
    plan: workspace.plan,
    created_at: workspace.created_at
  };
}

function WorkspaceOverviewCard({
  label,
  value,
  detail,
  icon
}: {
  label: string;
  value: number;
  detail?: string;
  icon: ReactNode;
}) {
  return (
    <div className='rounded-md border bg-background p-4'>
      <div className='flex items-center justify-between gap-3'>
        <p className='text-xs font-medium uppercase text-muted-foreground'>
          {label}
        </p>
        <span className='text-muted-foreground'>{icon}</span>
      </div>
      <p className='mt-2 text-2xl font-semibold'>{value}</p>
      {detail ? (
        <p className='mt-1 text-xs text-muted-foreground'>{detail}</p>
      ) : null}
    </div>
  );
}

function ActionTooltip({
  label,
  children
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side='top'>{label}</TooltipContent>
    </Tooltip>
  );
}

export function AdminWorkspacesPage() {
  const t = useTranslations('adminConsole.workspaces');
  const qc = useQueryClient();
  const router = useRouter();
  const { setCurrentOrg } = useOrganization();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState(ALL);
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [editWorkspace, setEditWorkspace] = useState<AdminWorkspaceOut | null>(
    null
  );
  const [archiveWorkspace, setArchiveWorkspace] =
    useState<AdminWorkspaceOut | null>(null);
  const [accessWorkspace, setAccessWorkspace] =
    useState<AdminWorkspaceOut | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const scope = useAdminWorkspaceScope();
  const isSuperadmin = scope.isSuperadmin;
  const searchParams = useSearchParams();
  const detailWorkspaceId = searchParams.get('workspaceId');
  const shouldOpenDetail = searchParams.get('detail') === '1';
  const shouldOpenCreate = searchParams.get('create') === '1';

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

  const workspaces = useQuery({
    queryKey: ['admin-workspaces', params],
    queryFn: () => adminApi.listWorkspaces(params)
  });

  const deepLinkedWorkspace = useQuery({
    queryKey: ['admin-workspace-detail-link', detailWorkspaceId],
    queryFn: () => adminApi.getWorkspace(detailWorkspaceId ?? ''),
    enabled: shouldOpenDetail && !!detailWorkspaceId
  });

  const summary = useQuery({
    queryKey: ['admin-summary', scope.scopedWorkspaceId],
    queryFn: () => adminApi.summary({ workspaceId: scope.scopedWorkspaceId }),
    staleTime: 30_000
  });

  const pageCounts = useMemo(() => {
    return (workspaces.data?.items ?? []).reduce(
      (counts, workspace) => ({
        admins: counts.admins + workspace.adminCount,
        members: counts.members + workspace.memberCount
      }),
      { admins: 0, members: 0 }
    );
  }, [workspaces.data?.items]);

  useEffect(() => {
    if (shouldOpenDetail && deepLinkedWorkspace.data) {
      setAccessWorkspace(deepLinkedWorkspace.data);
    }
  }, [deepLinkedWorkspace.data, shouldOpenDetail]);

  useEffect(() => {
    if (shouldOpenCreate) setCreateOpen(true);
  }, [shouldOpenCreate]);

  const enterWorkspace = (workspace: AdminWorkspaceOut) => {
    setCurrentOrg(workspaceToOrganization(workspace));
    router.push(ROUTES.DEVICES.ROOT);
  };

  const createMutation = useMutation({
    mutationFn: adminApi.createWorkspace,
    onSuccess: (created) => {
      setCreateOpen(false);
      setSecret(created.temporaryPassword || null);
      toast.success(t('toast.created'));
      void qc.invalidateQueries({ queryKey: ['admin-workspaces'] });
      void qc.invalidateQueries({ queryKey: ['admin-summary'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      body
    }: {
      id: string;
      body: Partial<AdminWorkspaceOut>;
    }) =>
      adminApi.updateWorkspace(id, {
        businessName: body.businessName,
        description: body.description,
        businessEmail: body.businessEmail ?? undefined,
        status: body.status,
        plan: body.plan,
        kind: body.kind
      }),
    onSuccess: () => {
      setEditWorkspace(null);
      toast.success(t('toast.updated'));
      void qc.invalidateQueries({ queryKey: ['admin-workspaces'] });
      void qc.invalidateQueries({ queryKey: ['admin-summary'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const resetPasswordMutation = useMutation({
    mutationFn: (workspaceId: string) =>
      adminApi.resetOwnerPassword(workspaceId),
    onSuccess: (result) => {
      setSecret(result.temporaryPassword);
      toast.success(t('toast.ownerPasswordReset'));
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const lifecycleMutation = useMutation({
    mutationFn: ({
      id,
      action
    }: {
      id: string;
      action: 'suspend' | 'reactivate' | 'archive';
    }) => {
      if (action === 'suspend') return adminApi.suspendWorkspace(id);
      if (action === 'reactivate') return adminApi.reactivateWorkspace(id);
      return adminApi.archiveWorkspace(id);
    },
    onSuccess: () => {
      setArchiveWorkspace(null);
      toast.success(t('toast.lifecycleUpdated'));
      void qc.invalidateQueries({ queryKey: ['admin-workspaces'] });
      void qc.invalidateQueries({ queryKey: ['admin-summary'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  return (
    <div className='min-h-full bg-muted/20'>
      <AdminPageHeader
        title={t('title')}
        description={t('description')}
        action={
          <div className='flex flex-col gap-2 sm:flex-row sm:items-center'>
            <AdminWorkspaceScopeSelect
              value={scope.workspaceId}
              onChange={(value) => {
                scope.setWorkspaceId(value);
                setOffset(0);
              }}
              workspaces={scope.workspaces}
              allowGlobalScope={scope.allowGlobalScope}
              workspaceLabel={t('scope.workspace')}
              allWorkspacesLabel={t('scope.allWorkspaces')}
            />
            {isSuperadmin ? (
              <Button asChild variant='outline'>
                <Link href={ROUTES.ADMIN.WORKSPACE_ADMINS}>
                  <UserCog className='mr-2 size-4' />
                  {t('accountProvisioning')}
                </Link>
              </Button>
            ) : null}
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className='mr-2 size-4' />
              {t('newWorkspace')}
            </Button>
          </div>
        }
      />
      <div className='space-y-4 p-4 md:p-6'>
        <div className='grid gap-3 md:grid-cols-2 xl:grid-cols-4'>
          <WorkspaceOverviewCard
            label={t('overview.workspaces')}
            value={workspaces.data?.total ?? summary.data?.totalWorkspaces ?? 0}
            detail={t('overview.activeWorkspaces', {
              count: summary.data?.activeWorkspaces ?? 0
            })}
            icon={<Users className='size-4' />}
          />
          <WorkspaceOverviewCard
            label={t('overview.devices')}
            value={summary.data?.totalDevices ?? 0}
            detail={t('overview.unassignedDevices', {
              count: summary.data?.unassignedDevices ?? 0
            })}
            icon={<Smartphone className='size-4' />}
          />
          <WorkspaceOverviewCard
            label={t('overview.agents')}
            value={summary.data?.totalAgents ?? 0}
            detail={t('overview.onlineAgents', {
              count: summary.data?.onlineAgents ?? 0
            })}
            icon={<Server className='size-4' />}
          />
          <WorkspaceOverviewCard
            label={t('overview.admins')}
            value={pageCounts.admins}
            detail={t('overview.membersOnPage', {
              count: pageCounts.members
            })}
            icon={<ShieldCheck className='size-4' />}
          />
        </div>

        <section className='rounded-lg border bg-background p-4 shadow-sm'>
          <div className='flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between'>
            <div className='min-w-0 space-y-3'>
              <div>
                <p className='text-xs font-medium uppercase tracking-wide text-muted-foreground'>
                  {t('setup.eyebrow')}
                </p>
                <h2 className='mt-1 text-base font-semibold leading-6'>
                  {t('setup.title')}
                </h2>
                <p className='mt-1 max-w-3xl text-sm leading-6 text-muted-foreground'>
                  {t('setup.description')}
                </p>
              </div>
              <div className='grid gap-2 md:grid-cols-3'>
                {[
                  t('setup.stepPool'),
                  t('setup.stepActivation'),
                  t('setup.stepAllocation')
                ].map((label, index) => (
                  <div
                    key={label}
                    className='flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-sm'
                  >
                    <span className='flex size-6 shrink-0 items-center justify-center rounded-full bg-background text-xs font-semibold text-foreground shadow-sm'>
                      {index + 1}
                    </span>
                    <span className='min-w-0 text-muted-foreground'>
                      {label}
                    </span>
                  </div>
                ))}
              </div>
            </div>
            <div className='flex shrink-0 flex-wrap gap-2'>
              <Button asChild variant='outline' size='sm'>
                <Link href={`${ROUTES.ADMIN.AGENTS}?tab=tokens`}>
                  {t('setup.activationAction')}
                </Link>
              </Button>
              <Button asChild size='sm'>
                <Link href={ROUTES.ADMIN.AGENTS}>{t('setup.allocateAction')}</Link>
              </Button>
            </div>
          </div>
        </section>

        <div className='flex flex-col gap-3 rounded-md border bg-background p-3 md:flex-row'>
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
            <SelectTrigger className='w-full md:w-[180px]'>
              <SelectValue placeholder={t('filters.status')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('filters.allStatuses')}</SelectItem>
              <SelectItem value='active'>{t('statuses.active')}</SelectItem>
              <SelectItem value='suspended'>
                {t('statuses.suspended')}
              </SelectItem>
              <SelectItem value='archived'>{t('statuses.archived')}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {workspaces.isError ? (
          <AdminErrorState
            message={formatAdminApiError(workspaces.error)}
            onRetry={() => void workspaces.refetch()}
          />
        ) : null}

        <div className='overflow-hidden rounded-md border bg-background'>
          <div className='overflow-x-auto'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('table.workspace')}</TableHead>
                  <TableHead>{t('table.owner')}</TableHead>
                  <TableHead>{t('table.status')}</TableHead>
                  <TableHead>{t('table.agents')}</TableHead>
                  <TableHead>{t('table.devices')}</TableHead>
                  <TableHead>{t('table.members')}</TableHead>
                  <TableHead>{t('table.admins')}</TableHead>
                  <TableHead>{t('table.updated')}</TableHead>
                  <TableHead className='w-[260px] text-right'>
                    {t('table.actions')}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {workspaces.isLoading ? (
                  <AdminTableSkeleton columns={9} />
                ) : null}
                {workspaces.data?.items.map((workspace) => (
                  <TableRow key={workspace.id}>
                    <TableCell>
                      <div className='min-w-[220px]'>
                        <p className='flex items-center gap-1.5 font-medium'>
                          {workspace.businessName}
                          {workspace.kind === 'pool' ? (
                            <Badge
                              variant='outline'
                              className='border-sky-500/30 bg-sky-500/10 text-[10px] text-sky-700 dark:text-sky-300'
                            >
                              {t('kindPoolBadge')}
                            </Badge>
                          ) : null}
                        </p>
                        <p className='line-clamp-1 text-xs text-muted-foreground'>
                          {workspace.description ||
                            workspace.businessEmail ||
                            workspace.id}
                        </p>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className='min-w-[180px] text-sm'>
                        <p>{workspace.owner?.name || '-'}</p>
                        <p className='text-xs text-muted-foreground'>
                          {workspace.owner?.email || '-'}
                        </p>
                      </div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge value={workspace.status} />
                    </TableCell>
                    <TableCell>{workspace.agentCount}</TableCell>
                    <TableCell>{workspace.deviceCount}</TableCell>
                    <TableCell>{workspace.memberCount}</TableCell>
                    <TableCell>
                      <div className='flex max-w-[220px] flex-wrap gap-1'>
                        {(workspace.workspaceAdmins ?? []).length ? (
                          (workspace.workspaceAdmins ?? [])
                            .slice(0, 2)
                            .map((admin) => (
                              <span
                                key={admin.user_id}
                                className='rounded border bg-muted px-1.5 py-0.5 text-xs'
                              >
                                {admin.name || admin.email}
                              </span>
                            ))
                        ) : (
                          <span className='text-sm text-muted-foreground'>
                            {t('table.noAdmins')}
                          </span>
                        )}
                        {workspace.adminCount > 2 ? (
                          <span className='text-xs text-muted-foreground'>
                            +{workspace.adminCount - 2}
                          </span>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell className='text-sm text-muted-foreground'>
                      {dateLabel(workspace.updated_at)}
                    </TableCell>
                    <TableCell>
                      <div className='flex justify-end gap-1.5'>
                        <Button
                          size='sm'
                          onClick={() => enterWorkspace(workspace)}
                        >
                          <LogIn className='mr-2 size-4' />
                          {t('actions.enterWorkspace')}
                        </Button>
                        <Button
                          size='sm'
                          variant='outline'
                          onClick={() => setAccessWorkspace(workspace)}
                        >
                          <ShieldCheck className='mr-2 size-4' />
                          {t('actions.details')}
                        </Button>
                        <ActionTooltip
                          label={
                            workspace.kind === 'pool'
                              ? t('actions.unmarkPool')
                              : t('actions.markPool')
                          }
                        >
                          <Button
                            size='icon'
                            variant='ghost'
                            className='size-8'
                            aria-label={
                              workspace.kind === 'pool'
                                ? t('actions.unmarkPool')
                                : t('actions.markPool')
                            }
                            disabled={updateMutation.isPending}
                            onClick={() =>
                              updateMutation.mutate({
                                id: workspace.id,
                                body: {
                                  kind:
                                    workspace.kind === 'pool'
                                      ? 'tenant'
                                      : 'pool'
                                }
                              })
                            }
                          >
                            <Server
                              className={cn(
                                'size-4',
                                workspace.kind === 'pool'
                                  ? 'text-sky-600 dark:text-sky-400'
                                  : undefined
                              )}
                            />
                          </Button>
                        </ActionTooltip>
                        <ActionTooltip label={t('actions.edit')}>
                          <Button
                            size='icon'
                            variant='ghost'
                            className='size-8'
                            aria-label={t('actions.edit')}
                            onClick={() => setEditWorkspace(workspace)}
                          >
                            <Edit className='size-4' />
                          </Button>
                        </ActionTooltip>
                        <ActionTooltip label={t('actions.resetOwnerPassword')}>
                          <Button
                            size='icon'
                            variant='ghost'
                            className='size-8'
                            aria-label={t('actions.resetOwnerPassword')}
                            disabled={
                              resetPasswordMutation.isPending ||
                              !workspace.owner
                            }
                            onClick={() =>
                              resetPasswordMutation.mutate(workspace.id)
                            }
                          >
                            <KeyRound className='size-4' />
                          </Button>
                        </ActionTooltip>
                        <ActionTooltip label={t('actions.archive')}>
                          <Button
                            size='icon'
                            variant='ghost'
                            className='size-8 text-destructive hover:text-destructive'
                            aria-label={t('actions.archive')}
                            onClick={() => setArchiveWorkspace(workspace)}
                          >
                            <Trash2 className='size-4' />
                          </Button>
                        </ActionTooltip>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
                {!workspaces.isLoading &&
                workspaces.data?.items.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={9}
                      className='h-28 text-center text-sm text-muted-foreground'
                    >
                      {t('empty')}
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
          <AdminPagination
            offset={offset}
            limit={ADMIN_PAGE_SIZE}
            total={workspaces.data?.total ?? 0}
            onOffsetChange={setOffset}
          />
        </div>
      </div>

      <WorkspaceCreateDialog
        open={createOpen}
        pending={createMutation.isPending}
        isSuperadmin={isSuperadmin}
        onClose={() => setCreateOpen(false)}
        onSubmit={(body) => createMutation.mutate(body)}
      />
      <WorkspaceEditDialog
        workspace={editWorkspace}
        pending={updateMutation.isPending || lifecycleMutation.isPending}
        onClose={() => setEditWorkspace(null)}
        onSubmit={(id, body) => updateMutation.mutate({ id, body })}
        onLifecycle={(id, action) => lifecycleMutation.mutate({ id, action })}
      />
      <WorkspaceAccessDialog
        workspace={accessWorkspace}
        onEnterWorkspace={enterWorkspace}
        onClose={() => setAccessWorkspace(null)}
      />
      <AlertDialog
        open={!!archiveWorkspace}
        onOpenChange={(open) => !open && setArchiveWorkspace(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('archive.title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('archive.description')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className='bg-destructive text-destructive-foreground hover:bg-destructive/90'
              onClick={() =>
                archiveWorkspace &&
                lifecycleMutation.mutate({
                  id: archiveWorkspace.id,
                  action: 'archive'
                })
              }
            >
              {t('archive.confirm')}
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

function WorkspaceCreateDialog({
  open,
  pending,
  isSuperadmin,
  onClose,
  onSubmit
}: {
  open: boolean;
  pending: boolean;
  isSuperadmin: boolean;
  onClose: () => void;
  onSubmit: (body: AdminWorkspaceCreate) => void;
}) {
  const t = useTranslations('adminConsole.workspaces.createDialog');
  const tCommon = useTranslations('adminConsole.workspaces.common');
  const [body, setBody] = useState<AdminWorkspaceCreate>({
    businessName: '',
    description: '',
    businessEmail: '',
    ownerEmail: '',
    ownerName: '',
    kind: 'tenant'
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit(body);
  };
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className='sm:max-w-2xl'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <form className='grid gap-4 md:grid-cols-2' onSubmit={submit}>
          <Field label={t('workspaceName')}>
            <Input
              required
              placeholder={t('workspaceNamePlaceholder')}
              value={body.businessName}
              onChange={(e) =>
                setBody({ ...body, businessName: e.target.value })
              }
            />
          </Field>
          <Field label={t('businessEmail')}>
            <Input
              value={body.businessEmail}
              onChange={(e) =>
                setBody({ ...body, businessEmail: e.target.value })
              }
            />
          </Field>
          <Field label={t('ownerEmail')}>
            <Input
              type='email'
              required={!isSuperadmin}
              value={body.ownerEmail}
              onChange={(e) => setBody({ ...body, ownerEmail: e.target.value })}
            />
          </Field>
          <Field label={t('ownerName')}>
            <Input
              value={body.ownerName}
              onChange={(e) => setBody({ ...body, ownerName: e.target.value })}
            />
          </Field>
          <Field label={t('kind')}>
            <Select
              value={body.kind ?? 'tenant'}
              onValueChange={(value) =>
                setBody({ ...body, kind: value as AdminWorkspaceKind })
              }
            >
              <SelectTrigger className='w-full'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value='tenant'>{t('kindTenant')}</SelectItem>
                <SelectItem value='pool'>{t('kindPool')}</SelectItem>
              </SelectContent>
            </Select>
            <p className='mt-1 text-xs text-muted-foreground'>{t('kindHint')}</p>
          </Field>
          <Field label={t('description')} className='md:col-span-2'>
            <Textarea
              value={body.description}
              onChange={(e) =>
                setBody({ ...body, description: e.target.value })
              }
            />
          </Field>
          <DialogFooter className='md:col-span-2'>
            <Button type='button' variant='outline' onClick={onClose}>
              {tCommon('cancel')}
            </Button>
            <Button type='submit' disabled={pending}>
              {pending ? <SubmitSpinner /> : null}
              {tCommon('create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function WorkspaceEditDialog({
  workspace,
  pending,
  onClose,
  onSubmit,
  onLifecycle
}: {
  workspace: AdminWorkspaceOut | null;
  pending: boolean;
  onClose: () => void;
  onSubmit: (id: string, body: Partial<AdminWorkspaceOut>) => void;
  onLifecycle: (id: string, action: 'suspend' | 'reactivate') => void;
}) {
  const t = useTranslations('adminConsole.workspaces.editDialog');
  const tCommon = useTranslations('adminConsole.workspaces.common');
  const [draft, setDraft] = useState<Partial<AdminWorkspaceOut>>({});
  useEffect(() => {
    setDraft({});
  }, [workspace?.id]);
  const active = workspace ? { ...workspace, ...draft } : null;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (workspace && active) onSubmit(workspace.id, active);
  };
  return (
    <Dialog open={!!workspace} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className='sm:max-w-2xl'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        {active ? (
          <form className='grid gap-4 md:grid-cols-2' onSubmit={submit}>
            <Field label={t('workspaceName')}>
              <Input
                value={active.businessName}
                onChange={(e) =>
                  setDraft({ ...draft, businessName: e.target.value })
                }
              />
            </Field>
            <Field label={t('businessEmail')}>
              <Input
                value={active.businessEmail || ''}
                onChange={(e) =>
                  setDraft({ ...draft, businessEmail: e.target.value })
                }
              />
            </Field>
            <Field label={t('status')}>
              <Select
                value={active.status}
                onValueChange={(value) => setDraft({ ...draft, status: value })}
              >
                <SelectTrigger className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value='active'>{t('active')}</SelectItem>
                  <SelectItem value='suspended'>{t('suspended')}</SelectItem>
                  <SelectItem value='disabled'>{t('disabled')}</SelectItem>
                  <SelectItem value='archived'>{t('archived')}</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label={t('kind')}>
              <Select
                value={active.kind || 'tenant'}
                onValueChange={(value) =>
                  setDraft({ ...draft, kind: value as AdminWorkspaceKind })
                }
              >
                <SelectTrigger className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value='tenant'>{t('kindTenant')}</SelectItem>
                  <SelectItem value='pool'>{t('kindPool')}</SelectItem>
                </SelectContent>
              </Select>
              <p className='mt-1 text-xs text-muted-foreground'>{t('kindHint')}</p>
            </Field>
            <Field label={t('description')} className='md:col-span-2'>
              <Textarea
                value={active.description || ''}
                onChange={(e) =>
                  setDraft({ ...draft, description: e.target.value })
                }
              />
            </Field>
            <div className='flex gap-2 md:col-span-2'>
              <Button
                type='button'
                variant='outline'
                disabled={pending || active.status === 'suspended'}
                onClick={() => onLifecycle(active.id, 'suspend')}
              >
                {t('suspend')}
              </Button>
              <Button
                type='button'
                variant='outline'
                disabled={pending || active.status === 'active'}
                onClick={() => onLifecycle(active.id, 'reactivate')}
              >
                {t('reactivate')}
              </Button>
            </div>
            <DialogFooter className='md:col-span-2'>
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

function WorkspaceAccessDialog({
  workspace,
  onEnterWorkspace,
  onClose
}: {
  workspace: AdminWorkspaceOut | null;
  onEnterWorkspace: (workspace: AdminWorkspaceOut) => void;
  onClose: () => void;
}) {
  const t = useTranslations('adminConsole.workspaces.access');
  const tCommon = useTranslations('adminConsole.workspaces.common');
  const qc = useQueryClient();
  const workspaceId = workspace?.id ?? '';
  const [deviceOffset, setDeviceOffset] = useState(0);
  useEffect(() => setDeviceOffset(0), [workspaceId]);
  const workspaceDevices = useQuery({
    queryKey: ['admin-workspace-detail-devices', workspaceId, deviceOffset],
    queryFn: () =>
      adminApi.listDevices({
        workspaceId,
        offset: deviceOffset,
        limit: DIALOG_DEVICE_PAGE_SIZE
      }),
    enabled: !!workspaceId,
    placeholderData: (previous) => previous,
    refetchInterval: 20_000
  });
  const updateOwnerMutation = useMutation({
    mutationFn: (body: { is_active?: boolean; mustChangePassword?: boolean }) =>
      adminApi.updateOwner(workspaceId, body),
    onSuccess: () => {
      toast.success(t('toast.ownerUpdated'));
      void qc.invalidateQueries({ queryKey: ['admin-workspaces'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  return (
    <>
      <Dialog
        open={!!workspace}
        onOpenChange={(next) => {
          if (!next) {
            onClose();
          }
        }}
      >
        <DialogContent className='max-h-[90vh] overflow-y-auto sm:max-w-4xl'>
          <DialogHeader>
            {/* pr-10 keeps the action clear of DialogContent's absolute close button. */}
            <div className='flex flex-col gap-3 pr-10 sm:flex-row sm:items-center sm:justify-between'>
              <DialogTitle>{t('title')}</DialogTitle>
              {workspace ? (
                <Button size='sm' onClick={() => onEnterWorkspace(workspace)}>
                  <LogIn className='mr-2 size-4' />
                  {t('enterWorkspace')}
                </Button>
              ) : null}
            </div>
          </DialogHeader>
          {workspace ? (
            <div className='space-y-5'>
              <div className='grid gap-3 rounded-md border bg-muted/30 p-3 md:grid-cols-4'>
                <div className='md:col-span-2'>
                  <p className='text-xs font-medium uppercase text-muted-foreground'>
                    {t('workspace')}
                  </p>
                  <p className='font-medium'>{workspace.businessName}</p>
                </div>
                <div className='md:col-span-2'>
                  <p className='text-xs font-medium uppercase text-muted-foreground'>
                    {t('owner')}
                  </p>
                  <p className='font-medium'>{workspace.owner?.name || '-'}</p>
                  <p className='text-xs text-muted-foreground'>
                    {workspace.owner?.email || '-'}
                  </p>
                  {workspace.owner ? (
                    <div className='mt-2 flex flex-wrap items-center gap-2'>
                      <StatusBadge
                        value={
                          workspace.owner.is_active ? 'active' : 'disabled'
                        }
                      />
                      {workspace.owner.mustChangePassword ? (
                        <span className='rounded-md border bg-muted/40 px-2 py-1 text-xs text-muted-foreground'>
                          {t('mustChangePassword')}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <div className='rounded-md border bg-background p-3'>
                  <p className='text-xs font-medium uppercase text-muted-foreground'>
                    {t('counts.devices')}
                  </p>
                  <p className='mt-1 text-xl font-semibold'>
                    {workspace.deviceCount}
                  </p>
                </div>
                <div className='rounded-md border bg-background p-3'>
                  <p className='text-xs font-medium uppercase text-muted-foreground'>
                    {t('counts.agents')}
                  </p>
                  <p className='mt-1 text-xl font-semibold'>
                    {workspace.agentCount}
                  </p>
                </div>
                <div className='rounded-md border bg-background p-3'>
                  <p className='text-xs font-medium uppercase text-muted-foreground'>
                    {t('counts.members')}
                  </p>
                  <p className='mt-1 text-xl font-semibold'>
                    {workspace.memberCount}
                  </p>
                </div>
                <div className='rounded-md border bg-background p-3'>
                  <p className='text-xs font-medium uppercase text-muted-foreground'>
                    {t('counts.admins')}
                  </p>
                  <p className='mt-1 text-xl font-semibold'>
                    {workspace.adminCount}
                  </p>
                </div>
              </div>

              {workspace.owner ? (
                <div className='flex flex-wrap items-center gap-2 rounded-md border bg-background p-3'>
                  <span className='mr-auto text-sm font-medium'>
                    {t('ownerActions')}
                  </span>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    disabled={updateOwnerMutation.isPending}
                    onClick={() =>
                      updateOwnerMutation.mutate({
                        is_active: !workspace.owner?.is_active
                      })
                    }
                  >
                    {workspace.owner.is_active
                      ? t('disableOwner')
                      : t('enableOwner')}
                  </Button>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    disabled={
                      updateOwnerMutation.isPending ||
                      workspace.owner.mustChangePassword
                    }
                    onClick={() =>
                      updateOwnerMutation.mutate({ mustChangePassword: true })
                    }
                  >
                    {t('forcePasswordChange')}
                  </Button>
                </div>
              ) : null}

              <div className='space-y-2'>
                <div className='flex items-center justify-between gap-3'>
                  <div className='flex items-center gap-2'>
                    <Smartphone className='size-4 text-muted-foreground' />
                    <h2 className='text-sm font-semibold'>
                      {t('workspacePhones')}
                    </h2>
                  </div>
                  <Button asChild type='button' variant='outline' size='sm'>
                    <Link href={ROUTES.ADMIN.DEVICES}>
                      {t('viewAllPhones')}
                    </Link>
                  </Button>
                </div>
                <div className='overflow-hidden rounded-md border'>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t('table.phone')}</TableHead>
                        <TableHead>{t('table.status')}</TableHead>
                        <TableHead>{t('table.state')}</TableHead>
                        <TableHead>{t('table.managedBy')}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {workspaceDevices.isLoading ? (
                        <AdminTableSkeleton columns={4} />
                      ) : null}
                      {workspaceDevices.data?.items.map((device) => (
                        <TableRow key={device.id}>
                          <TableCell>
                            <p className='font-medium'>
                              {device.name || device.serial}
                            </p>
                            <p className='text-xs text-muted-foreground'>
                              {device.serial}
                              {device.model ? ` · ${device.model}` : ''}
                            </p>
                          </TableCell>
                          <TableCell>
                            <StatusBadge value={device.status} />
                          </TableCell>
                          <TableCell>
                            <StatusBadge value={device.state} />
                          </TableCell>
                          <TableCell>
                            {device.managedByWorkspaceName ||
                              device.managedByWorkspaceId ||
                              '-'}
                          </TableCell>
                        </TableRow>
                      ))}
                      {!workspaceDevices.isLoading &&
                      workspaceDevices.data?.items.length === 0 ? (
                        <TableRow>
                          <TableCell
                            colSpan={4}
                            className='h-20 text-center text-sm text-muted-foreground'
                          >
                            {t('phonesEmpty')}
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </TableBody>
                  </Table>
                  <AdminPagination
                    offset={deviceOffset}
                    limit={DIALOG_DEVICE_PAGE_SIZE}
                    total={workspaceDevices.data?.total ?? 0}
                    onOffsetChange={setDeviceOffset}
                  />
                </div>
              </div>

              <DialogFooter>
                <Button type='button' variant='outline' onClick={onClose}>
                  {tCommon('cancel')}
                </Button>
              </DialogFooter>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}

function AdminUserCreateDialog({
  open,
  pending,
  onClose,
  onSubmit
}: {
  open: boolean;
  pending: boolean;
  onClose: () => void;
  onSubmit: (body: AdminUserCreate) => void;
}) {
  const t = useTranslations('adminConsole.workspaces.access.createDialog');
  const tCommon = useTranslations('adminConsole.workspaces.common');
  const [body, setBody] = useState<AdminUserCreate>({
    email: '',
    name: ''
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit({
      email: body.email.trim(),
      name: body.name.trim()
    });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setBody({ email: '', name: '' });
          onClose();
        }
      }}
    >
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <form className='space-y-4' onSubmit={submit}>
          <Field label={t('name')}>
            <Input
              required
              value={body.name}
              onChange={(event) =>
                setBody({ ...body, name: event.target.value })
              }
            />
          </Field>
          <Field label={t('email')}>
            <Input
              required
              type='email'
              value={body.email}
              onChange={(event) =>
                setBody({ ...body, email: event.target.value })
              }
            />
          </Field>
          <DialogFooter>
            <Button type='button' variant='outline' onClick={onClose}>
              {tCommon('cancel')}
            </Button>
            <Button type='submit' disabled={pending}>
              {pending ? <SubmitSpinner /> : null}
              {tCommon('create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  children,
  className
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <Label className='mb-2 block'>{label}</Label>
      {children}
    </div>
  );
}
