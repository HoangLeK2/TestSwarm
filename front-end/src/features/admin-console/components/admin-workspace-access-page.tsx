'use client';

import { useState } from 'react';
import type { ReactNode } from 'react';
import { ShieldCheck, Trash2, Users } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
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
  AdminErrorState,
  AdminPageHeader,
  AdminTableSkeleton,
  AdminWorkspaceScopeSelect,
  StatusBadge,
  SubmitSpinner
} from './admin-shared';
import { useAdminWorkspaceScope } from '../hooks/use-admin-workspace-scope';
import {
  adminApi,
  type AdminWorkspaceAccessOut,
  formatAdminApiError
} from '../services/admin-api';

type AccessMember = AdminWorkspaceAccessOut['members'][number];
type AccessAdmin = AdminWorkspaceAccessOut['admins'][number];
type MemberRole = 'member' | 'supervisor';
type RoleChangeTarget = {
  member: AccessMember;
  role: MemberRole;
};

function dateLabel(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '-';
}

export function AdminWorkspaceAccessPage() {
  const t = useTranslations('adminConsole.workspaceAccess');
  const qc = useQueryClient();
  const scope = useAdminWorkspaceScope();
  const workspaceId = scope.scopedWorkspaceId;
  const showWorkspace = !workspaceId;
  const [roleTarget, setRoleTarget] = useState<RoleChangeTarget | null>(null);
  const [memberTarget, setMemberTarget] = useState<AccessMember | null>(null);
  const [adminTarget, setAdminTarget] = useState<AccessAdmin | null>(null);

  const access = useQuery({
    queryKey: ['admin-workspace-access', workspaceId ?? 'all'],
    queryFn: () => adminApi.workspaceAccess(workspaceId)
  });
  const regularMembers = access.data?.members ?? [];
  const workspaceAdmins = access.data?.admins ?? [];

  const refreshAccess = () => {
    void qc.invalidateQueries({ queryKey: ['admin-workspace-access'] });
    void qc.invalidateQueries({ queryKey: ['admin-workspace-members'] });
    void qc.invalidateQueries({ queryKey: ['admin-workspace-admins'] });
    void qc.invalidateQueries({ queryKey: ['admin-workspaces'] });
  };
  const updateRole = useMutation({
    mutationFn: ({ member, role }: RoleChangeTarget) =>
      adminApi.updateWorkspaceMember(member.workspaceId, member.userId, {
        role
      }),
    onSuccess: () => {
      setRoleTarget(null);
      toast.success(t('toast.roleUpdated'));
      refreshAccess();
    },
    onError: (error) => {
      setRoleTarget(null);
      toast.error(formatAdminApiError(error));
    }
  });
  const removeMember = useMutation({
    mutationFn: (member: AccessMember) =>
      adminApi.removeWorkspaceMember(member.workspaceId, member.userId),
    onSuccess: () => {
      setMemberTarget(null);
      toast.success(t('toast.memberRemoved'));
      refreshAccess();
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });
  const removeAdmin = useMutation({
    mutationFn: (admin: AccessAdmin) =>
      adminApi.removeWorkspaceAdmin(admin.workspaceId, admin.user_id),
    onSuccess: () => {
      setAdminTarget(null);
      toast.success(t('toast.adminRemoved'));
      refreshAccess();
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  return (
    <div className='min-h-full bg-muted/20'>
      <AdminPageHeader
        title={t('title')}
        description={t('description')}
        action={
          <AdminWorkspaceScopeSelect
            value={scope.workspaceId}
            onChange={scope.setWorkspaceId}
            workspaces={scope.workspaces}
            allowGlobalScope={scope.allowGlobalScope}
            workspaceLabel={t('selectWorkspace')}
            allWorkspacesLabel={t('allWorkspaces')}
          />
        }
      />
      <div className='space-y-6 p-4 md:p-6'>
        <AccessSection title={t('members')} icon={<Users className='size-4' />}>
          {access.isError ? (
            <AdminErrorState
              message={formatAdminApiError(access.error)}
              onRetry={() => void access.refetch()}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('table.user')}</TableHead>
                  {showWorkspace ? (
                    <TableHead>{t('table.workspace')}</TableHead>
                  ) : null}
                  <TableHead>{t('table.role')}</TableHead>
                  <TableHead>{t('table.joined')}</TableHead>
                  <TableHead className='w-[100px] text-right'>
                    {t('table.actions')}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {access.isLoading ? (
                  <AdminTableSkeleton columns={showWorkspace ? 5 : 4} />
                ) : null}
                {regularMembers.map((member) => (
                  <TableRow key={member.id}>
                    <TableCell>
                      <p className='font-medium'>{member.name || '-'}</p>
                      <p className='text-xs text-muted-foreground'>
                        {member.email}
                      </p>
                    </TableCell>
                    {showWorkspace ? (
                      <TableCell className='text-sm'>
                        {member.workspaceName}
                      </TableCell>
                    ) : null}
                    <TableCell>
                      <Select
                        value={
                          roleTarget?.member.id === member.id
                            ? roleTarget.role
                            : (member.role as MemberRole)
                        }
                        onValueChange={(role) => {
                          if (role !== member.role) {
                            setRoleTarget({
                              member,
                              role: role as MemberRole
                            });
                          }
                        }}
                        disabled={updateRole.isPending}
                      >
                        <SelectTrigger className='w-[160px]'>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value='member'>
                            {t('roles.member')}
                          </SelectItem>
                          <SelectItem value='supervisor'>
                            {t('roles.supervisor')}
                          </SelectItem>
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell className='text-sm text-muted-foreground'>
                      {dateLabel(member.created_at)}
                    </TableCell>
                    <TableCell className='text-right'>
                      <Button
                        type='button'
                        size='icon'
                        variant='ghost'
                        className='text-destructive hover:text-destructive'
                        aria-label={t('removeMember')}
                        onClick={() => setMemberTarget(member)}
                      >
                        <Trash2 className='size-4' />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {!access.isLoading && regularMembers.length === 0 ? (
                  <EmptyRow
                    columns={showWorkspace ? 5 : 4}
                    label={t('emptyMembers')}
                  />
                ) : null}
              </TableBody>
            </Table>
          )}
        </AccessSection>

        <AccessSection
          title={t('admins')}
          icon={<ShieldCheck className='size-4' />}
        >
          {access.isError ? (
            <AdminErrorState
              message={formatAdminApiError(access.error)}
              onRetry={() => void access.refetch()}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('table.user')}</TableHead>
                  {showWorkspace ? (
                    <TableHead>{t('table.workspace')}</TableHead>
                  ) : null}
                  <TableHead>{t('table.status')}</TableHead>
                  <TableHead>{t('table.joined')}</TableHead>
                  <TableHead className='w-[100px] text-right'>
                    {t('table.actions')}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {access.isLoading ? (
                  <AdminTableSkeleton columns={showWorkspace ? 5 : 4} />
                ) : null}
                {workspaceAdmins.map((admin) => (
                  <TableRow key={`${admin.workspaceId}:${admin.user_id}`}>
                    <TableCell>
                      <p className='font-medium'>{admin.name}</p>
                      <p className='text-xs text-muted-foreground'>
                        {admin.email}
                      </p>
                    </TableCell>
                    {showWorkspace ? (
                      <TableCell className='text-sm'>
                        {admin.workspaceName}
                      </TableCell>
                    ) : null}
                    <TableCell>
                      <StatusBadge
                        value={admin.is_active ? 'active' : 'disabled'}
                      />
                    </TableCell>
                    <TableCell className='text-sm text-muted-foreground'>
                      {dateLabel(admin.joined_at)}
                    </TableCell>
                    <TableCell className='text-right'>
                      <Button
                        type='button'
                        size='icon'
                        variant='ghost'
                        className='text-destructive hover:text-destructive'
                        aria-label={t('removeAdmin')}
                        onClick={() => setAdminTarget(admin)}
                      >
                        <Trash2 className='size-4' />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {!access.isLoading && workspaceAdmins.length === 0 ? (
                  <EmptyRow
                    columns={showWorkspace ? 5 : 4}
                    label={t('emptyAdmins')}
                  />
                ) : null}
              </TableBody>
            </Table>
          )}
        </AccessSection>
      </div>

      <ConfirmDialog
        open={!!roleTarget}
        title={t('changeRoleTitle')}
        description={t('changeRoleDescription', {
          email: roleTarget?.member.email || '',
          role: roleTarget ? t(`roles.${roleTarget.role}`) : ''
        })}
        pending={updateRole.isPending}
        onClose={() => setRoleTarget(null)}
        onConfirm={() => roleTarget && updateRole.mutate(roleTarget)}
      />
      <ConfirmDialog
        open={!!memberTarget}
        title={t('removeMemberTitle')}
        description={t('removeMemberDescription', {
          email: memberTarget?.email || ''
        })}
        pending={removeMember.isPending}
        onClose={() => setMemberTarget(null)}
        onConfirm={() => memberTarget && removeMember.mutate(memberTarget)}
      />
      <ConfirmDialog
        open={!!adminTarget}
        title={t('removeAdminTitle')}
        description={t('removeAdminDescription', {
          email: adminTarget?.email || ''
        })}
        pending={removeAdmin.isPending}
        onClose={() => setAdminTarget(null)}
        onConfirm={() => adminTarget && removeAdmin.mutate(adminTarget)}
      />
    </div>
  );
}

function AccessSection({
  title,
  icon,
  children
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className='overflow-hidden rounded-md border bg-background'>
      <div className='flex items-center gap-2 border-b px-4 py-3 font-medium'>
        <span className='text-muted-foreground'>{icon}</span>
        {title}
      </div>
      <div className='overflow-x-auto'>{children}</div>
    </section>
  );
}

function EmptyRow({ columns, label }: { columns: number; label: string }) {
  return (
    <TableRow>
      <TableCell
        colSpan={columns}
        className='h-28 text-center text-sm text-muted-foreground'
      >
        {label}
      </TableCell>
    </TableRow>
  );
}

function ConfirmDialog({
  open,
  title,
  description,
  pending,
  onClose,
  onConfirm
}: {
  open: boolean;
  title: string;
  description: string;
  pending: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const t = useTranslations('adminConsole.workspaceAccess.common');
  return (
    <AlertDialog open={open} onOpenChange={(next) => !next && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>
            {t('cancel')}
          </AlertDialogCancel>
          <Button type='button' disabled={pending} onClick={onConfirm}>
            {pending ? <SubmitSpinner /> : null}
            {t('confirm')}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
