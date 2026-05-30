'use client';

import { useMemo, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { formatDistanceToNow } from 'date-fns';
import { enUS, vi } from 'date-fns/locale';
import { Trash2, Users } from 'lucide-react';
import { toast } from 'sonner';
import {
  useOrganizationMembers,
  useRemoveOrganizationMember,
  useUpdateOrganizationMember,
  type OrganizationMemberOut
} from '../hooks/use-organization-members';
import { OrganizationInviteMemberDialog } from './organization-invite-member-dialog';
import { usePermission } from '@/features/auth/hooks/use-permission';
import { useUser } from '@/features/auth';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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
import { formatOrgMemberInviteError } from '../lib/format-org-invite-error';

type AssignableOrgRole = 'member' | 'supervisor';

function roleLabel(
  role: string,
  t: (key: string) => string
): string {
  if (role === 'owner') return t('owner');
  if (role === 'supervisor') return t('supervisor');
  return t('staff');
}

function MemberRoleCell({
  member,
  canManage,
  currentUserId,
  onRoleChange
}: {
  member: OrganizationMemberOut;
  canManage: boolean;
  currentUserId?: string;
  onRoleChange: (member: OrganizationMemberOut, role: AssignableOrgRole) => void;
}) {
  const t = useTranslations('organization.memberManagement');
  const role = member.role;
  const editable =
    canManage &&
    role !== 'owner' &&
    member.userId !== currentUserId;

  if (!editable) {
    return (
      <Badge variant={role === 'owner' ? 'default' : 'secondary'}>
        {roleLabel(role, t)}
      </Badge>
    );
  }

  return (
    <Select
      value={role === 'supervisor' ? 'supervisor' : 'member'}
      onValueChange={(next) => {
        if (next === role) return;
        onRoleChange(member, next as AssignableOrgRole);
      }}
    >
      <SelectTrigger className='h-8 w-[160px]' aria-label={t('changeRole')}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value='member'>{t('staff')}</SelectItem>
        <SelectItem value='supervisor'>{t('supervisor')}</SelectItem>
      </SelectContent>
    </Select>
  );
}

export function OrganizationMembersPage() {
  const t = useTranslations('organization.memberManagement');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  const dateLocale = locale === 'vi' ? vi : enUS;
  const { data: members, isLoading, error } = useOrganizationMembers();
  const removeMutation = useRemoveOrganizationMember();
  const updateRoleMutation = useUpdateOrganizationMember();
  const [removeUserId, setRemoveUserId] = useState<string | null>(null);
  const [roleChangeTarget, setRoleChangeTarget] = useState<{
    member: OrganizationMemberOut;
    role: AssignableOrgRole;
  } | null>(null);
  const { user } = useUser();

  const canManage = usePermission('organizations', 'manage');

  const removeTarget = useMemo(
    () => (members ?? []).find((m) => m.userId === removeUserId),
    [members, removeUserId]
  );

  const handleConfirmRemove = () => {
    if (!removeUserId) return;
    removeMutation.mutate(removeUserId, {
      onSuccess: () => {
        toast.success(t('removeMember'));
        setRemoveUserId(null);
      },
      onError: (err) => {
        toast.error(formatOrgMemberInviteError(err, t, t('removeMember')));
      }
    });
  };

  const handleConfirmRoleChange = () => {
    if (!roleChangeTarget) return;
    updateRoleMutation.mutate(
      {
        userId: roleChangeTarget.member.userId,
        role: roleChangeTarget.role
      },
      {
        onSuccess: () => {
          toast.success(t('changeRoleSuccess'));
          setRoleChangeTarget(null);
        },
        onError: (err) => {
          toast.error(formatOrgMemberInviteError(err, t, t('changeRole')));
        }
      }
    );
  };

  return (
    <div className='space-y-6'>
      <div className='flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between'>
        <div className='flex items-center gap-3'>
          <Users className='size-5 text-muted-foreground' />
          <div>
            <h1 className='text-xl font-semibold'>{t('title')}</h1>
            <p className='text-sm text-muted-foreground'>{t('description')}</p>
          </div>
        </div>
        {canManage ? <OrganizationInviteMemberDialog /> : null}
      </div>

      {isLoading ? (
        <p className='text-sm text-muted-foreground'>{tCommon('loading')}</p>
      ) : error ? (
        <p className='text-sm text-destructive'>
          {formatOrgMemberInviteError(error, t, t('currentMembers'))}
        </p>
      ) : !members?.length ? (
        <div className='rounded-lg border border-dashed border-border p-12 text-center'>
          <Users className='mx-auto mb-3 size-10 text-muted-foreground' />
          <p className='text-sm text-muted-foreground'>{t('noMembersYet')}</p>
          {canManage ? (
            <div className='mt-4 flex justify-center'>
              <OrganizationInviteMemberDialog />
            </div>
          ) : null}
        </div>
      ) : (
        <div className='rounded-lg border border-border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('emailAddress')}</TableHead>
                <TableHead>{t('memberName')}</TableHead>
                <TableHead>{t('role')}</TableHead>
                <TableHead className='w-[120px]' />
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.map((member) => (
                <TableRow key={member.id}>
                  <TableCell className='font-medium'>{member.email}</TableCell>
                  <TableCell>{member.name || '—'}</TableCell>
                  <TableCell>
                    <MemberRoleCell
                      member={member}
                      canManage={canManage}
                      currentUserId={user?.id ?? undefined}
                      onRoleChange={(target, role) =>
                        setRoleChangeTarget({ member: target, role })
                      }
                    />
                  </TableCell>
                  <TableCell className='text-right text-xs text-muted-foreground'>
                    <div className='flex items-center justify-end gap-2'>
                      <span>
                        {formatDistanceToNow(new Date(member.created_at), {
                          addSuffix: true,
                          locale: dateLocale
                        })}
                      </span>
                      {canManage &&
                      member.role !== 'owner' &&
                      member.userId !== user?.id ? (
                        <Button
                          type='button'
                          variant='ghost'
                          size='icon'
                          className='size-8 text-destructive'
                          onClick={() => setRemoveUserId(member.userId)}
                          aria-label={t('removeMember')}
                        >
                          <Trash2 className='size-4' />
                        </Button>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <AlertDialog
        open={Boolean(removeUserId)}
        onOpenChange={(open) => !open && setRemoveUserId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('removeMember')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('removeMemberConfirmation')}
              {removeTarget ? ` (${removeTarget.email})` : ''}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{tCommon('cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmRemove}
              disabled={removeMutation.isPending}
            >
              {t('removeMember')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={Boolean(roleChangeTarget)}
        onOpenChange={(open) => !open && setRoleChangeTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('changeRole')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('changeRoleConfirmation', {
                role: roleChangeTarget
                  ? roleLabel(roleChangeTarget.role, t)
                  : ''
              })}
              {roleChangeTarget ? ` (${roleChangeTarget.member.email})` : ''}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{tCommon('cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmRoleChange}
              disabled={updateRoleMutation.isPending}
            >
              {t('changeRole')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
