'use client';

import { useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { enUS, vi } from 'date-fns/locale';
import { CheckCircle2, Loader2, Plus, RefreshCw, Star, X } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { useConfirm } from '@/providers/modal-provider';
import {
  useAccounts,
  ACCOUNTS_PAGE_LIMIT,
  useAssignAccountsToDevice,
  useDeviceAccounts,
  useFacebookPlatformSession,
  useSetPrimaryDeviceAccount,
  useUnassignDeviceFromAccount,
  useVerifyDeviceAccount
} from '../hooks/use-accounts';

const statusClass: Record<string, string> = {
  verified: 'border-emerald-500/40 text-emerald-600',
  mismatch: 'border-destructive/40 text-destructive',
  inconclusive: 'border-amber-500/40 text-amber-600',
  unsupported: 'text-muted-foreground'
};

export function DeviceAccountsPanel({ deviceId }: { deviceId: string }) {
  const t = useTranslations('accountsFeature.devicePanel');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  const dateLocale = locale.startsWith('vi') ? vi : enUS;
  const confirm = useConfirm();
  const perms = useResourcePermissions('accounts');
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const { data: links = [], isLoading } = useDeviceAccounts(deviceId);
  const { data: facebookSession } = useFacebookPlatformSession(deviceId);
  const { data: accounts = [], isLoading: accountsLoading } = useAccounts({
    limit: ACCOUNTS_PAGE_LIMIT
  });
  const assign = useAssignAccountsToDevice();
  const remove = useUnassignDeviceFromAccount();
  const setPrimary = useSetPrimaryDeviceAccount();
  const verify = useVerifyDeviceAccount();

  const accountById = new Map(accounts.map((account) => [account.id, account]));
  const linkedIds = new Set(links.map((link) => link.account_id));
  const query = search.trim().toLowerCase();
  const available = accounts.filter(
    (account) =>
      !linkedIds.has(account.id) &&
      (!query ||
        account.username.toLowerCase().includes(query) ||
        account.display_name?.toLowerCase().includes(query) ||
        account.platform.toLowerCase().includes(query))
  );
  const groups = Object.entries(
    Object.groupBy(
      links,
      (link) =>
        accountById.get(link.account_id)?.platform || t('unknownPlatform')
    )
  ).sort(([a], [b]) => a.localeCompare(b));
  const busy = remove.isPending || setPrimary.isPending || verify.isPending;
  const facebookAccount = facebookSession?.account_id
    ? accountById.get(facebookSession.account_id)
    : null;
  const facebookExpectedAccountId =
    typeof facebookSession?.evidence?.expected_account_id === 'string'
      ? facebookSession.evidence.expected_account_id
      : null;
  const facebookExpectedAccount = facebookExpectedAccountId
    ? accountById.get(facebookExpectedAccountId)
    : null;
  const facebookSessionLabel =
    facebookAccount?.display_name ||
    facebookAccount?.username ||
    facebookExpectedAccount?.display_name ||
    facebookExpectedAccount?.username ||
    facebookSession?.account_id ||
    facebookExpectedAccountId ||
    '';
  const facebookSessionReason = facebookSession?.state_reason
    ? {
        primary_account_changed: t('sessionReason.primary_account_changed'),
        provenance_account_unassigned: t(
          'sessionReason.provenance_account_unassigned'
        ),
        migration_operator_confirmed: t(
          'sessionReason.migration_operator_confirmed'
        )
      }[facebookSession.state_reason] || facebookSession.state_reason
    : '';

  async function handleAssign() {
    try {
      await assign.mutateAsync({ deviceId, accountIds: selected });
      setSelected([]);
      setAdding(false);
      setSearch('');
      toast.success(t('assignSuccess', { count: selected.length }));
    } catch {
      toast.error(t('assignError'));
    }
  }

  async function handleSetPrimary(accountId: string) {
    try {
      await setPrimary.mutateAsync({ deviceId, accountId });
      toast.success(t('primarySuccess'));
    } catch {
      toast.error(t('primaryError'));
    }
  }

  async function handleVerify(accountId: string) {
    try {
      const result = await verify.mutateAsync({ deviceId, accountId });
      if (result.status === 'verified') toast.success(t('verifySuccess'));
      else
        toast.warning(
          t('verifyResult', { status: t(`status.${result.status}`) })
        );
    } catch {
      toast.error(t('verifyError'));
    }
  }

  async function handleRemove(accountId: string, label: string) {
    const accepted = await confirm({
      title: t('removeTitle'),
      description: t('removeConfirm', { account: label }),
      confirmText: tCommon('confirm'),
      cancelText: tCommon('cancel'),
      confirmVariant: 'destructive',
      zIndex: 10_000
    });
    if (!accepted) return;
    try {
      await remove.mutateAsync({ deviceId, accountId });
      toast.success(t('removeSuccess'));
    } catch {
      toast.error(t('removeError'));
    }
  }

  return (
    <Card>
      <CardHeader className='flex flex-row items-center justify-between gap-2 py-3'>
        <CardTitle className='text-sm'>{t('title')}</CardTitle>
        {perms.canUpdate && !adding ? (
          <Button size='sm' variant='outline' onClick={() => setAdding(true)}>
            <Plus className='mr-1.5 size-3.5' />
            {t('add')}
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className='space-y-3'>
        {adding ? (
          <div className='space-y-2 rounded-lg border bg-muted/20 p-3'>
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t('searchPlaceholder')}
              className='h-8'
            />
            <div className='max-h-48 space-y-1 overflow-y-auto'>
              {accountsLoading ? (
                <p className='text-xs text-muted-foreground'>{t('loading')}</p>
              ) : available.length === 0 ? (
                <p className='py-2 text-xs text-muted-foreground'>
                  {t('noAvailable')}
                </p>
              ) : (
                available.map((account) => (
                  <label
                    key={account.id}
                    className='flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted'
                  >
                    <Checkbox
                      checked={selected.includes(account.id)}
                      onCheckedChange={(checked) =>
                        setSelected((current) =>
                          checked
                            ? [...current, account.id]
                            : current.filter((id) => id !== account.id)
                        )
                      }
                    />
                    <span className='min-w-0 flex-1 truncate text-xs'>
                      {account.display_name || account.username}
                    </span>
                    <Badge variant='outline' className='text-[10px] capitalize'>
                      {account.platform}
                    </Badge>
                  </label>
                ))
              )}
            </div>
            <div className='flex justify-end gap-2'>
              <Button
                size='sm'
                variant='ghost'
                onClick={() => {
                  setAdding(false);
                  setSelected([]);
                  setSearch('');
                }}
              >
                {t('cancel')}
              </Button>
              <Button
                size='sm'
                disabled={!selected.length || assign.isPending}
                onClick={handleAssign}
              >
                {assign.isPending ? (
                  <Loader2 className='mr-1.5 size-3.5 animate-spin' />
                ) : null}
                {t('assign', { count: selected.length })}
              </Button>
            </div>
          </div>
        ) : null}

        {facebookSession ? (
          <div className='rounded-lg border bg-muted/20 px-3 py-2'>
            <div className='flex flex-wrap items-center gap-1.5'>
              <Badge variant='outline' className='text-[10px]'>
                Facebook
              </Badge>
              <Badge
                variant={
                  facebookSession.state === 'active' ? 'secondary' : 'outline'
                }
                className='text-[10px]'
              >
                {t(`session.${facebookSession.state}`)}
              </Badge>
              {facebookSessionLabel ? (
                <span className='min-w-0 truncate text-xs text-muted-foreground'>
                  {facebookSessionLabel}
                </span>
              ) : null}
            </div>
            {facebookSessionReason ? (
              <p className='mt-1 text-[11px] text-muted-foreground'>
                {facebookSessionReason}
              </p>
            ) : null}
          </div>
        ) : null}

        {isLoading ? (
          <p className='text-xs text-muted-foreground'>{t('loading')}</p>
        ) : links.length === 0 ? (
          <p className='text-xs text-muted-foreground'>{t('empty')}</p>
        ) : (
          groups.map(([platform, platformLinks]) => (
            <div key={platform} className='space-y-1.5'>
              <p className='text-[11px] font-semibold uppercase tracking-wide text-muted-foreground'>
                {platform}
              </p>
              {(platformLinks || []).map((link) => {
                const account = accountById.get(link.account_id);
                const status = link.verification_status || 'unknown';
                const reason = String(link.verification_evidence?.reason || '');
                const label =
                  account?.display_name ||
                  account?.username ||
                  t('unavailableAccount');
                const isSettingPrimary =
                  setPrimary.isPending &&
                  setPrimary.variables?.accountId === link.account_id;
                const isVerifying =
                  verify.isPending &&
                  verify.variables?.accountId === link.account_id;
                const isRemoving =
                  remove.isPending &&
                  remove.variables?.accountId === link.account_id;
                return (
                  <div key={link.id} className='rounded-lg border px-3 py-2'>
                    <div className='flex items-start gap-2'>
                      <div className='min-w-0 flex-1'>
                        <div className='flex flex-wrap items-center gap-1.5'>
                          <span className='truncate text-sm font-medium'>
                            {label}
                          </span>
                          {link.is_primary ? (
                            <Badge
                              className='gap-1 text-[10px]'
                              variant='secondary'
                            >
                              <Star className='size-2.5 fill-current' />{' '}
                              {t('primary')}
                            </Badge>
                          ) : null}
                          <Badge
                            variant='outline'
                            className={`text-[10px] ${statusClass[status] || ''}`}
                          >
                            {status === 'verified' ? (
                              <CheckCircle2 className='mr-1 size-2.5' />
                            ) : null}
                            {t(`status.${status}`)}
                          </Badge>
                        </div>
                        {account?.display_name ? (
                          <p className='truncate text-[11px] text-muted-foreground'>
                            {account.username}
                          </p>
                        ) : null}
                        {reason ? (
                          <p className='mt-1 text-[11px] text-muted-foreground'>
                            {reason}
                          </p>
                        ) : null}
                        {link.verification_attempted_at ? (
                          <p className='mt-1 text-[11px] text-muted-foreground'>
                            {t('lastVerified', {
                              time: formatDistanceToNow(
                                new Date(link.verification_attempted_at),
                                { addSuffix: true, locale: dateLocale }
                              )
                            })}
                          </p>
                        ) : null}
                      </div>
                      {perms.canUpdate ? (
                        <div className='flex shrink-0 items-center'>
                          {!link.is_primary ? (
                            <Button
                              size='icon'
                              variant='ghost'
                              className='size-7'
                              title={t('setPrimary')}
                              disabled={busy}
                              onClick={() =>
                                void handleSetPrimary(link.account_id)
                              }
                            >
                              {isSettingPrimary ? (
                                <Loader2 className='size-3.5 animate-spin' />
                              ) : (
                                <Star className='size-3.5' />
                              )}
                            </Button>
                          ) : null}
                          <Button
                            size='icon'
                            variant='ghost'
                            className='size-7'
                            title={t('verify')}
                            disabled={busy}
                            onClick={() => void handleVerify(link.account_id)}
                          >
                            <RefreshCw
                              className={`size-3.5 ${isVerifying ? 'animate-spin' : ''}`}
                            />
                          </Button>
                          <Button
                            size='icon'
                            variant='ghost'
                            className='size-7 text-destructive hover:text-destructive'
                            title={t('remove')}
                            disabled={busy}
                            onClick={() =>
                              void handleRemove(link.account_id, label)
                            }
                          >
                            {isRemoving ? (
                              <Loader2 className='size-3.5 animate-spin' />
                            ) : (
                              <X className='size-3.5' />
                            )}
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
