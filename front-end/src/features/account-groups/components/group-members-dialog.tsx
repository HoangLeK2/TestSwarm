'use client';

import { useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Search, Trash2, Users } from 'lucide-react';
import {
  useAccountGroupMembers,
  useAddAccountGroupMembers,
  useRemoveAccountGroupMember
} from '../hooks/use-account-groups';
import type { AccountGroupOut } from '../services/api';
import {
  ACCOUNTS_PAGE_LIMIT,
  useAccounts
} from '@/features/accounts/hooks/use-accounts';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { cn } from '@/lib/utils';
import { normalizeAccountState } from '@/features/accounts/lib/account-fsm';

const STATUS_LABEL_KEY: Record<string, string> = {
  unassigned: 'statusUnassigned',
  active: 'statusActive',
  suspended: 'statusVerifying',
  banned: 'statusBanned',
  retired: 'statusRetired'
};

function accountStatusLabel(
  status: string,
  tStatus: (key: string) => string
): string {
  const key = normalizeAccountState(status);
  const messageKey = STATUS_LABEL_KEY[key];
  return messageKey ? tStatus(messageKey) : status;
}

export function GroupMembersDialog({
  group,
  open,
  onOpenChange
}: {
  group: AccountGroupOut;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations('accountGroupsFeature');
  const tStatus = useTranslations('accountsFeature.list');
  const { data: members, isLoading: membersLoading } = useAccountGroupMembers(
    open ? group.id : ''
  );
  const { data: allAccounts, isLoading: accountsLoading } = useAccounts(
    open
      ? { platform: group.platform, limit: ACCOUNTS_PAGE_LIMIT }
      : undefined
  );
  const addMembers = useAddAccountGroupMembers();
  const removeMember = useRemoveAccountGroupMember();

  const [staged, setStaged] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');

  const currentMemberIds = useMemo(
    () => new Set((members ?? []).map((m) => m.account_id)),
    [members]
  );

  const eligible = useMemo(() => {
    const base = (allAccounts ?? []).filter(
      (acc) => !currentMemberIds.has(acc.id)
    );
    if (!search.trim()) return base;
    const q = search.toLowerCase();
    return base.filter(
      (acc) =>
        acc.username.toLowerCase().includes(q) ||
        acc.display_name?.toLowerCase().includes(q)
    );
  }, [allAccounts, currentMemberIds, search]);

  const toggleStaged = (id: string) => {
    setStaged((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleAdd = () => {
    if (!staged.size) return;
    const ids = Array.from(staged);
    addMembers.mutate(
      { groupId: group.id, data: { account_ids: ids } },
      {
        onSuccess: (res) => {
          toast.success(t('addedSuccess', { count: res.added }));
          setStaged(new Set());
        },
        onError: (err) => {
          toast.error(formatFarmApiError(err, t('addedSuccess', { count: 0 })));
        }
      }
    );
  };

  const handleRemove = (accountId: string) => {
    removeMember.mutate(
      { groupId: group.id, accountId },
      {
        onSuccess: () => {
          toast.success(t('removedSuccess'));
        }
      }
    );
  };

  const statusVariant = (status: string) => {
    const s = (status || '').toLowerCase();
    if (s === 'active' || s === 'ready') return 'default';
    if (s === 'banned' || s === 'error' || s === 'disabled')
      return 'destructive';
    return 'secondary';
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) {
          setStaged(new Set());
          setSearch('');
        }
      }}
    >
      <DialogContent className='z-[1000] max-h-[90vh] max-w-4xl overflow-hidden'>
        <DialogHeader>
          <DialogTitle>
            {t('membersTitle')} — {group.name}
          </DialogTitle>
        </DialogHeader>
        <div className='grid gap-4 pt-2 md:grid-cols-2 md:items-stretch'>
          {/* Left: current members */}
          <section className='flex min-h-[480px] flex-col overflow-hidden rounded-lg border border-border bg-card'>
            <div className='flex items-center justify-between border-b border-border px-3 py-2'>
              <div className='flex items-center gap-2 text-sm font-medium'>
                <Users size={14} className='text-muted-foreground' />
                <span>{t('membersCurrent')}</span>
                <Badge variant='secondary' className='text-[10px]'>
                  {members?.length ?? 0}
                </Badge>
              </div>
            </div>
            <div className='min-h-0 flex-1 overflow-y-auto'>
              <div className='divide-y divide-border'>
                {membersLoading && (
                  <p className='p-4 text-sm text-muted-foreground'>
                    {t('membersCurrent')}...
                  </p>
                )}
                {!membersLoading && !members?.length && (
                  <p className='p-6 text-center text-sm text-muted-foreground'>
                    {t('membersNoCurrent')}
                  </p>
                )}
                {(members ?? []).map((m) => (
                  <div
                    key={m.account_id}
                    className='flex items-center gap-2 px-3 py-2'
                  >
                    <div className='min-w-0 flex-1'>
                      <div className='flex min-w-0 items-center gap-2'>
                        <span className='truncate text-sm font-medium'>
                          {m.username}
                        </span>
                        <Badge
                          variant={statusVariant(m.status)}
                          className='shrink-0 text-[10px]'
                        >
                          {accountStatusLabel(m.status, tStatus)}
                        </Badge>
                      </div>
                      {m.display_name && (
                        <p className='truncate text-[11px] text-muted-foreground'>
                          {m.display_name}
                        </p>
                      )}
                    </div>
                    <Button
                      size='icon'
                      variant='ghost'
                      className='size-7 shrink-0 text-destructive hover:text-destructive'
                      title={t('membersRemove')}
                      onClick={() => handleRemove(m.account_id)}
                      disabled={removeMember.isPending}
                    >
                      <Trash2 size={14} />
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* Right: eligible accounts */}
          <section className='flex min-h-[480px] flex-col overflow-hidden rounded-lg border border-border bg-card'>
            <div className='space-y-2 border-b border-border px-3 py-2'>
              <div className='flex items-center gap-2 text-sm font-medium'>
                <Users size={14} className='text-muted-foreground' />
                <span>{t('membersEligible')}</span>
                <Badge variant='secondary' className='text-[10px]'>
                  {eligible.length}
                </Badge>
              </div>
              <div className='relative'>
                <Search
                  size={14}
                  className='absolute left-2.5 top-2.5 text-muted-foreground'
                />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('searchPlaceholder')}
                  className='h-8 pl-8'
                />
              </div>
            </div>
            <div className='min-h-0 flex-1 overflow-y-auto'>
              <div className='divide-y divide-border'>
                {accountsLoading && (
                  <p className='p-4 text-sm text-muted-foreground'>
                    {t('membersEligible')}...
                  </p>
                )}
                {!accountsLoading && !eligible.length && (
                  <p className='p-6 text-center text-sm text-muted-foreground'>
                    {t('membersNoEligible')}
                  </p>
                )}
                {eligible.map((acc) => {
                  const checked = staged.has(acc.id);
                  return (
                    <label
                      key={acc.id}
                      className={cn(
                        'flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-muted/40',
                        checked && 'bg-muted/50'
                      )}
                    >
                      <Checkbox
                        checked={checked}
                        onCheckedChange={() => toggleStaged(acc.id)}
                        className='shrink-0'
                      />
                      <div className='min-w-0 flex-1'>
                        <div className='flex min-w-0 items-center gap-2'>
                          <span className='truncate text-sm font-medium'>
                            {acc.username}
                          </span>
                          <Badge
                            variant={statusVariant(acc.status)}
                            className='shrink-0 text-[10px]'
                          >
                            {accountStatusLabel(acc.status, tStatus)}
                          </Badge>
                        </div>
                        {acc.display_name && (
                          <p className='truncate text-[11px] text-muted-foreground'>
                            {acc.display_name}
                          </p>
                        )}
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>
            <div className='border-t border-border px-3 py-2'>
              <Button
                size='sm'
                className='w-full'
                onClick={handleAdd}
                disabled={!staged.size || addMembers.isPending}
              >
                {t('membersAddSelected')}
                {staged.size > 0 && ` (${staged.size})`}
              </Button>
            </div>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
