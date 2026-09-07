'use client';

import { type FormEvent, useEffect, useMemo, useState } from 'react';
import { Plus, ShieldCheck, UserCog } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
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
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
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
import {
  adminApi,
  type AdminAssignableWorkspaceOut,
  type AdminUserCreate,
  type AdminUserOut,
  type AdminUserWorkspaceOut,
  formatAdminApiError
} from '../services/admin-api';

const ALL = '__all__';
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function dateLabel(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '-';
}

export function AdminWorkspaceAdminsPage() {
  const t = useTranslations('adminConsole.workspaceAdmins');
  const qc = useQueryClient();
  const scope = useAdminWorkspaceScope();
  const canManageAdminAccounts = scope.isSuperadmin;
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState(ALL);
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [assignAdmin, setAssignAdmin] = useState<AdminUserOut | null>(null);
  const [resetTarget, setResetTarget] = useState<AdminUserOut | null>(null);
  const [secret, setSecret] = useState<string | null>(null);

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

  const admins = useQuery({
    queryKey: ['workspace-admins', params],
    queryFn: () => adminApi.listAdminUsers(params),
    enabled: scope.allowGlobalScope
  });

  const createMutation = useMutation({
    mutationFn: adminApi.createAdminUser,
    onSuccess: (created) => {
      setCreateOpen(false);
      if (created.temporaryPassword) setSecret(created.temporaryPassword);
      toast.success(t('toast.created'));
      void qc.invalidateQueries({ queryKey: ['workspace-admins'] });
      void qc.invalidateQueries({ queryKey: ['admin-workspaces'] });
      void qc.invalidateQueries({ queryKey: ['admin-workspace-admins'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const updateMutation = useMutation({
    mutationFn: (admin: AdminUserOut) =>
      adminApi.updateAdminUser(admin.user_id, { is_active: !admin.is_active }),
    onSuccess: () => {
      toast.success(t('toast.updated'));
      void qc.invalidateQueries({ queryKey: ['workspace-admins'] });
      void qc.invalidateQueries({ queryKey: ['admin-workspace-admins'] });
      void qc.invalidateQueries({ queryKey: ['admin-workspaces'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const assignMutation = useMutation({
    mutationFn: async ({
      addWorkspaceIds,
      removeWorkspaceIds,
      adminUserId
    }: {
      addWorkspaceIds: string[];
      removeWorkspaceIds: string[];
      adminUserId: string;
    }) => {
      const assigned = addWorkspaceIds.length
        ? await adminApi.bulkAssignAdminUserWorkspaces(adminUserId, {
            workspaceIds: addWorkspaceIds
          })
        : null;
      const removed = removeWorkspaceIds.length
        ? await adminApi.bulkRemoveAdminUserWorkspaces(adminUserId, {
            workspaceIds: removeWorkspaceIds
          })
        : null;
      return {
        assignedCount: assigned?.assigned.length ?? 0,
        removedCount: removed?.removed.length ?? 0,
        skippedCount:
          (assigned?.skipped.length ?? 0) + (removed?.skipped.length ?? 0)
      };
    },
    onSuccess: (result) => {
      setAssignAdmin(null);
      toast.success(
        t('toast.assignmentsUpdated', {
          assigned: result.assignedCount,
          removed: result.removedCount,
          skipped: result.skippedCount
        })
      );
      void qc.invalidateQueries({ queryKey: ['workspace-admins'] });
      void qc.invalidateQueries({ queryKey: ['admin-workspaces'] });
      void qc.invalidateQueries({ queryKey: ['admin-workspace-admins'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const resetPasswordMutation = useMutation({
    mutationFn: (adminUserId: string) =>
      adminApi.resetAdminUserPassword(adminUserId),
    onSuccess: (result) => {
      setResetTarget(null);
      setSecret(result.temporaryPassword);
      toast.success(t('toast.passwordReset'));
      void qc.invalidateQueries({ queryKey: ['workspace-admins'] });
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
            {canManageAdminAccounts ? (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className='mr-2 size-4' />
                {t('createAdmin')}
              </Button>
            ) : null}
          </div>
        }
      />
      <div className='space-y-4 p-4 md:p-6'>
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
              <SelectItem value='active'>{t('filters.active')}</SelectItem>
              <SelectItem value='disabled'>{t('filters.disabled')}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {admins.isError ? (
          <AdminErrorState
            message={formatAdminApiError(admins.error)}
            onRetry={() => void admins.refetch()}
          />
        ) : null}

        <div className='overflow-hidden rounded-md border bg-background'>
          <div className='overflow-x-auto'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('table.admin')}</TableHead>
                  <TableHead>{t('table.status')}</TableHead>
                  <TableHead>{t('table.workspaces')}</TableHead>
                  <TableHead>{t('table.assignedWorkspaces')}</TableHead>
                  <TableHead>{t('table.created')}</TableHead>
                  {canManageAdminAccounts ? (
                    <TableHead className='w-[320px] text-right'>
                      {t('table.actions')}
                    </TableHead>
                  ) : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {admins.isLoading ? (
                  <AdminTableSkeleton
                    columns={canManageAdminAccounts ? 6 : 5}
                  />
                ) : null}
                {admins.data?.items.map((admin) => (
                  <TableRow key={admin.user_id}>
                    <TableCell>
                      <div className='min-w-[220px]'>
                        <p className='font-medium'>{admin.name}</p>
                        <p className='text-xs text-muted-foreground'>
                          {admin.email}
                        </p>
                      </div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge
                        value={admin.is_active ? 'active' : 'disabled'}
                      />
                    </TableCell>
                    <TableCell>{admin.adminWorkspaceCount}</TableCell>
                    <TableCell>
                      <AssignedWorkspaceList
                        workspaces={admin.adminWorkspaces}
                        emptyLabel={t('noAssignedWorkspaces')}
                      />
                    </TableCell>
                    <TableCell className='text-sm text-muted-foreground'>
                      {dateLabel(admin.created_at)}
                    </TableCell>
                    {canManageAdminAccounts ? (
                      <TableCell>
                        <div className='flex justify-end gap-1'>
                          <Button
                            size='sm'
                            variant='outline'
                            disabled={!admin.is_active}
                            onClick={() => setAssignAdmin(admin)}
                          >
                            <ShieldCheck className='mr-2 size-4' />
                            {t('assign')}
                          </Button>
                          <Button
                            size='sm'
                            variant='ghost'
                            disabled={resetPasswordMutation.isPending}
                            onClick={() => setResetTarget(admin)}
                          >
                            {t('resetPassword')}
                          </Button>
                          <Button
                            size='sm'
                            variant='ghost'
                            disabled={updateMutation.isPending}
                            onClick={() => updateMutation.mutate(admin)}
                          >
                            <UserCog className='mr-2 size-4' />
                            {admin.is_active ? t('disable') : t('enable')}
                          </Button>
                        </div>
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
                {!admins.isLoading && admins.data?.items.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={canManageAdminAccounts ? 6 : 5}
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
            total={admins.data?.total ?? 0}
            onOffsetChange={setOffset}
          />
        </div>
      </div>

      {canManageAdminAccounts ? (
        <>
          <AdminUserCreateDialog
            open={createOpen}
            pending={createMutation.isPending}
            workspaces={scope.workspaces}
            defaultWorkspaceId={scope.scopedWorkspaceId ?? ''}
            requireWorkspace={!scope.isSuperadmin}
            onClose={() => setCreateOpen(false)}
            onSubmit={(body) => createMutation.mutate(body)}
          />
          <WorkspaceAdminAssignDialog
            admin={assignAdmin}
            defaultWorkspaceId={scope.scopedWorkspaceId ?? ''}
            pending={assignMutation.isPending}
            onClose={() => setAssignAdmin(null)}
            onSubmit={(addWorkspaceIds, removeWorkspaceIds, adminUserId) =>
              assignMutation.mutate({
                addWorkspaceIds,
                removeWorkspaceIds,
                adminUserId
              })
            }
          />
        </>
      ) : null}
      <AlertDialog
        open={!!resetTarget}
        onOpenChange={(open) => !open && setResetTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('resetPasswordTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('resetPasswordDescription', {
                email: resetTarget?.email || ''
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={resetPasswordMutation.isPending}>
              {t('common.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={resetPasswordMutation.isPending}
              onClick={() =>
                resetTarget && resetPasswordMutation.mutate(resetTarget.user_id)
              }
            >
              {resetPasswordMutation.isPending ? <SubmitSpinner /> : null}
              {t('resetPassword')}
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

function AdminUserCreateDialog({
  open,
  pending,
  workspaces,
  defaultWorkspaceId,
  requireWorkspace,
  onClose,
  onSubmit
}: {
  open: boolean;
  pending: boolean;
  workspaces: Array<{
    id: string;
    businessName: string;
    status?: string | null;
  }>;
  defaultWorkspaceId: string;
  requireWorkspace: boolean;
  onClose: () => void;
  onSubmit: (body: AdminUserCreate) => void;
}) {
  const t = useTranslations('adminConsole.workspaceAdmins.createDialog');
  const tCommon = useTranslations('adminConsole.workspaceAdmins.common');
  const [body, setBody] = useState<AdminUserCreate>({
    email: '',
    name: '',
    workspaceIds: defaultWorkspaceId ? [defaultWorkspaceId] : []
  });
  const [submitted, setSubmitted] = useState(false);
  const trimmedName = body.name.trim();
  const trimmedEmail = body.email.trim();
  const selectedWorkspaceIds = body.workspaceIds ?? [];
  const emailValid = EMAIL_PATTERN.test(trimmedEmail);
  const nameError =
    submitted && !trimmedName ? t('validation.nameRequired') : '';
  const emailError =
    submitted && !trimmedEmail
      ? t('validation.emailRequired')
      : submitted && !emailValid
        ? t('validation.emailInvalid')
        : '';
  const workspaceError =
    submitted && requireWorkspace && selectedWorkspaceIds.length === 0
      ? t('validation.workspaceRequired')
      : '';
  const canSubmit = !pending;

  useEffect(() => {
    if (!open) {
      setBody({
        email: '',
        name: '',
        workspaceIds: defaultWorkspaceId ? [defaultWorkspaceId] : []
      });
      setSubmitted(false);
    }
  }, [defaultWorkspaceId, open]);

  const close = () => {
    setBody({
      email: '',
      name: '',
      workspaceIds: defaultWorkspaceId ? [defaultWorkspaceId] : []
    });
    setSubmitted(false);
    onClose();
  };

  const toggleWorkspace = (workspaceId: string, checked: boolean) => {
    setBody((current) => {
      const next = new Set(current.workspaceIds ?? []);
      if (checked) next.add(workspaceId);
      else next.delete(workspaceId);
      return { ...current, workspaceIds: Array.from(next) };
    });
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (
      !trimmedName ||
      !emailValid ||
      (requireWorkspace && selectedWorkspaceIds.length === 0) ||
      pending
    ) {
      return;
    }
    onSubmit({
      email: trimmedEmail,
      name: trimmedName,
      workspaceIds: selectedWorkspaceIds
    });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
      }}
    >
      <DialogContent className='sm:max-w-lg'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
          <DialogDescription>{t('description')}</DialogDescription>
        </DialogHeader>
        <form className='space-y-4' onSubmit={submit} noValidate>
          <div className='rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground'>
            {t('handoffNote')}
          </div>
          <div className='space-y-2'>
            <Label htmlFor='workspace-admin-name'>{t('name')}</Label>
            <Input
              id='workspace-admin-name'
              autoFocus
              autoComplete='name'
              aria-invalid={Boolean(nameError)}
              aria-describedby={
                nameError ? 'workspace-admin-name-error' : undefined
              }
              placeholder={t('namePlaceholder')}
              value={body.name}
              onChange={(event) =>
                setBody({ ...body, name: event.target.value })
              }
            />
            {nameError ? (
              <p
                id='workspace-admin-name-error'
                className='text-xs text-destructive'
              >
                {nameError}
              </p>
            ) : null}
          </div>
          <div className='space-y-2'>
            <Label htmlFor='workspace-admin-email'>{t('email')}</Label>
            <Input
              id='workspace-admin-email'
              type='email'
              autoComplete='email'
              inputMode='email'
              aria-invalid={Boolean(emailError)}
              aria-describedby={
                emailError ? 'workspace-admin-email-error' : undefined
              }
              placeholder={t('emailPlaceholder')}
              value={body.email}
              onChange={(event) =>
                setBody({ ...body, email: event.target.value })
              }
            />
            {emailError ? (
              <p
                id='workspace-admin-email-error'
                className='text-xs text-destructive'
              >
                {emailError}
              </p>
            ) : null}
          </div>
          {workspaces.length ? (
            <div className='space-y-2'>
              <Label>{t('workspaces')}</Label>
              <ScrollArea className='h-[180px] rounded-md border'>
                <div className='divide-y'>
                  {workspaces.map((workspace) => (
                    <WorkspaceCheckboxRow
                      key={workspace.id}
                      workspace={workspace}
                      checked={selectedWorkspaceIds.includes(workspace.id)}
                      onCheckedChange={(checked) =>
                        toggleWorkspace(workspace.id, checked)
                      }
                    />
                  ))}
                </div>
              </ScrollArea>
              {workspaceError ? (
                <p className='text-xs text-destructive'>{workspaceError}</p>
              ) : null}
            </div>
          ) : null}
          <DialogFooter>
            <Button type='button' variant='outline' onClick={close}>
              {tCommon('cancel')}
            </Button>
            <Button type='submit' disabled={!canSubmit}>
              {pending ? <SubmitSpinner /> : null}
              {tCommon('create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function WorkspaceAdminAssignDialog({
  admin,
  defaultWorkspaceId,
  pending,
  onClose,
  onSubmit
}: {
  admin: AdminUserOut | null;
  defaultWorkspaceId: string;
  pending: boolean;
  onClose: () => void;
  onSubmit: (
    addWorkspaceIds: string[],
    removeWorkspaceIds: string[],
    adminUserId: string
  ) => void;
}) {
  const t = useTranslations('adminConsole.workspaceAdmins.assignDialog');
  const tCommon = useTranslations('adminConsole.workspaceAdmins.common');
  const [workspaceSearch, setWorkspaceSearch] = useState('');
  const [selectedWorkspaceIds, setSelectedWorkspaceIds] = useState<Set<string>>(
    () => new Set()
  );
  const assignedWorkspaceIds = useMemo(
    () =>
      new Set((admin?.adminWorkspaces ?? []).map((workspace) => workspace.id)),
    [admin?.adminWorkspaces]
  );
  const workspaces = useQuery({
    queryKey: [
      'admin-workspaces-assignable',
      { search: workspaceSearch || undefined, offset: 0, limit: 50 }
    ],
    queryFn: () =>
      adminApi.listAssignableWorkspaces({
        search: workspaceSearch || undefined,
        offset: 0,
        limit: 50
      }),
    enabled: !!admin
  });
  const availableWorkspaces = (workspaces.data?.items ?? []).filter(
    (workspace) => !assignedWorkspaceIds.has(workspace.id)
  );

  useEffect(() => {
    const initial = new Set(
      (admin?.adminWorkspaces ?? []).map((workspace) => workspace.id)
    );
    if (defaultWorkspaceId) initial.add(defaultWorkspaceId);
    setSelectedWorkspaceIds(initial);
    setWorkspaceSearch('');
  }, [admin?.adminWorkspaces, admin?.user_id, defaultWorkspaceId]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!admin) return;
    const next = selectedWorkspaceIds;
    const addWorkspaceIds = Array.from(next).filter(
      (workspaceId) => !assignedWorkspaceIds.has(workspaceId)
    );
    const removeWorkspaceIds = Array.from(assignedWorkspaceIds).filter(
      (workspaceId) => !next.has(workspaceId)
    );
    if (addWorkspaceIds.length === 0 && removeWorkspaceIds.length === 0) return;
    onSubmit(addWorkspaceIds, removeWorkspaceIds, admin.user_id);
  };

  const toggleWorkspace = (workspaceId: string, checked: boolean) => {
    setSelectedWorkspaceIds((current) => {
      const next = new Set(current);
      if (checked) next.add(workspaceId);
      else next.delete(workspaceId);
      return next;
    });
  };

  const changedCount = admin
    ? Array.from(selectedWorkspaceIds).filter(
        (workspaceId) => !assignedWorkspaceIds.has(workspaceId)
      ).length +
      Array.from(assignedWorkspaceIds).filter(
        (workspaceId) => !selectedWorkspaceIds.has(workspaceId)
      ).length
    : 0;

  return (
    <Dialog open={!!admin} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className='sm:max-w-2xl'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
          <DialogDescription>{t('description')}</DialogDescription>
        </DialogHeader>
        <form className='space-y-4' onSubmit={submit}>
          <div className='rounded-md border bg-muted/30 p-3'>
            <p className='font-medium'>{admin?.name}</p>
            <p className='text-xs text-muted-foreground'>{admin?.email}</p>
          </div>
          <div className='space-y-2'>
            <Label htmlFor='workspace-admin-workspace-search'>
              {t('workspace')}
            </Label>
            <Input
              id='workspace-admin-workspace-search'
              value={workspaceSearch}
              onChange={(event) => setWorkspaceSearch(event.target.value)}
              placeholder={t('searchWorkspace')}
            />
          </div>
          <ScrollArea className='h-[320px] rounded-md border'>
            <div className='divide-y'>
              {(admin?.adminWorkspaces ?? []).length ? (
                <div className='space-y-2 p-3'>
                  <p className='text-xs font-medium uppercase text-muted-foreground'>
                    {t('currentlyAssigned')}
                  </p>
                  {(admin?.adminWorkspaces ?? []).map((workspace) => (
                    <WorkspaceCheckboxRow
                      key={workspace.id}
                      workspace={workspace}
                      checked={selectedWorkspaceIds.has(workspace.id)}
                      onCheckedChange={(checked) =>
                        toggleWorkspace(workspace.id, checked)
                      }
                    />
                  ))}
                </div>
              ) : null}
              <div className='space-y-2 p-3'>
                <p className='text-xs font-medium uppercase text-muted-foreground'>
                  {t('availableWorkspaces')}
                </p>
                {workspaces.isLoading ? (
                  <p className='py-6 text-center text-sm text-muted-foreground'>
                    {t('loading')}
                  </p>
                ) : null}
                {!workspaces.isLoading && availableWorkspaces.length === 0 ? (
                  <p className='py-6 text-center text-sm text-muted-foreground'>
                    {t('emptyWorkspaces')}
                  </p>
                ) : null}
                {availableWorkspaces.map((workspace) => (
                  <WorkspaceCheckboxRow
                    key={workspace.id}
                    workspace={workspace}
                    checked={selectedWorkspaceIds.has(workspace.id)}
                    onCheckedChange={(checked) =>
                      toggleWorkspace(workspace.id, checked)
                    }
                  />
                ))}
              </div>
            </div>
          </ScrollArea>
          <p className='text-xs text-muted-foreground'>
            {t('changeSummary', { count: changedCount })}
          </p>
          <DialogFooter>
            <Button type='button' variant='outline' onClick={onClose}>
              {tCommon('cancel')}
            </Button>
            <Button type='submit' disabled={pending || changedCount === 0}>
              {pending ? <SubmitSpinner /> : null}
              {tCommon('save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AssignedWorkspaceList({
  workspaces,
  emptyLabel
}: {
  workspaces: AdminUserWorkspaceOut[];
  emptyLabel: string;
}) {
  if (!workspaces.length) {
    return <span className='text-sm text-muted-foreground'>{emptyLabel}</span>;
  }
  const visible = workspaces.slice(0, 3);
  const hiddenCount = workspaces.length - visible.length;
  return (
    <div className='flex max-w-[360px] flex-wrap gap-1.5'>
      {visible.map((workspace) => (
        <span
          key={workspace.id}
          className='rounded-md border bg-muted/40 px-2 py-1 text-xs'
        >
          {workspace.businessName}
        </span>
      ))}
      {hiddenCount > 0 ? (
        <span className='rounded-md border bg-muted/40 px-2 py-1 text-xs text-muted-foreground'>
          +{hiddenCount}
        </span>
      ) : null}
    </div>
  );
}

function WorkspaceCheckboxRow({
  workspace,
  checked,
  onCheckedChange
}: {
  workspace:
    | AdminAssignableWorkspaceOut
    | AdminUserWorkspaceOut
    | { id: string; businessName: string; status?: string | null };
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <label className='flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 hover:bg-muted/50'>
      <Checkbox
        checked={checked}
        onCheckedChange={(value) => onCheckedChange(value === true)}
      />
      <span className='min-w-0 flex-1'>
        <span className='block truncate text-sm font-medium'>
          {workspace.businessName}
        </span>
        <span className='block truncate text-xs text-muted-foreground'>
          {workspace.id}
        </span>
      </span>
      <StatusBadge value={workspace.status || 'unknown'} />
    </label>
  );
}
