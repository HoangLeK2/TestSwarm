'use client';

import { useEffect, useMemo, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { useSearchParams } from 'next/navigation';
import { enUS, vi } from 'date-fns/locale';
import { Filter, Search, Users } from 'lucide-react';
import { toast } from 'sonner';
import {
  ACCOUNTS_PAGE_LIMIT,
  useAccounts,
  useDeleteAccount
} from '../../hooks/use-accounts';
import type { AccountOut } from '../../services/api';
import { DataTable } from '@/components/ui/table/data-table';
import { useDataTable } from '@/hooks/use-data-table';
import { CreateAccountDialog } from '../create-account-dialog';
import { ImportAccountsDialog } from '../import-accounts-dialog';
import { Can, useResourcePermissions } from '@/features/auth';
import { CoreEmptyState } from '@/components/core-empty-state';
import { getAccountColumns, type AccountStateKey } from './columns';
import { useConfirm } from '@/providers/modal-provider';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { normalizeAccountState } from '../../lib/account-fsm';
import { AccountLoginDialog } from '../account-login-dialog';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

const STATUS_FILTERS: Array<AccountStateKey | 'all'> = [
  'all',
  'unassigned',
  'assigned',
  'active',
  'suspended',
  'banned',
  'retired'
];

function accountMatchesSearch(account: AccountOut, query: string) {
  if (!query.trim()) return true;
  const normalized = query.trim().toLowerCase();
  return [
    account.username,
    account.display_name,
    account.observed_display_name,
    account.platform,
    account.tags,
    account.state_reason,
    account.assigned_device_name
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(normalized));
}

export function AccountList() {
  const t = useTranslations('accountsFeature.list');
  const tEmpty = useTranslations('coreEmptyState');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  const dateLocale = locale === 'vi' ? vi : enUS;
  const confirm = useConfirm();
  const searchParams = useSearchParams();
  const loginAccountId =
    searchParams.get('action') === 'login'
      ? searchParams.get('account_id')
      : null;
  const [deepLinkDismissed, setDeepLinkDismissed] = useState(false);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<AccountStateKey | 'all'>(
    'all'
  );
  // Không truyền limit thì server mặc định 50 và cắt im lặng.
  const {
    data: accounts,
    isLoading,
    error
  } = useAccounts({ limit: ACCOUNTS_PAGE_LIMIT });
  const deleteMutation = useDeleteAccount();
  const perms = useResourcePermissions('accounts');

  const data: AccountOut[] = useMemo(() => accounts ?? [], [accounts]);
  const deepLinkedAccount = useMemo(
    () => data.find((account) => account.id === loginAccountId) ?? null,
    [data, loginAccountId]
  );

  useEffect(() => {
    setDeepLinkDismissed(false);
  }, [loginAccountId]);

  const statusLabel: Record<AccountStateKey, string> = useMemo(
    () => ({
      unassigned: t('statusUnassigned'),
      assigned: t('statusAssigned'),
      active: t('statusActive'),
      suspended: t('statusVerifying'),
      banned: t('statusBanned'),
      retired: t('statusRetired')
    }),
    [t]
  );

  const stats = useMemo(() => {
    const stateCounts = data.reduce(
      (acc, account) => {
        const state = normalizeAccountState(
          account.state || account.status
        ) as AccountStateKey;
        if (state in acc) acc[state] += 1;
        return acc;
      },
      {
        unassigned: 0,
        assigned: 0,
        active: 0,
        suspended: 0,
        banned: 0,
        retired: 0
      } satisfies Record<AccountStateKey, number>
    );

    return {
      total: data.length,
      ready: stateCounts.active,
      assigned: stateCounts.assigned,
      unassigned: stateCounts.unassigned,
      verifying: stateCounts.suspended,
      banned: stateCounts.banned,
      needsReview: stateCounts.suspended + stateCounts.banned
    };
  }, [data]);

  const filteredData = useMemo(
    () =>
      data.filter((account) => {
        const state = normalizeAccountState(
          account.state || account.status
        ) as AccountStateKey;
        return (
          (statusFilter === 'all' || state === statusFilter) &&
          accountMatchesSearch(account, search)
        );
      }),
    [data, search, statusFilter]
  );

  const columns = useMemo(() => {
    return getAccountColumns(t, statusLabel, dateLocale, perms, (account) => {
      void (async () => {
        const ok = await confirm({
          title: t('delete'),
          description: t('confirmDelete', { username: account.username }),
          confirmText: tCommon('confirm'),
          cancelText: tCommon('cancel'),
          confirmVariant: 'destructive',
          zIndex: 10_000
        });
        if (!ok) return;
        deleteMutation.mutate(account.id, {
          onSuccess: () => toast.success(t('deleteSuccess')),
          onError: (mutationError) => {
            toast.error(formatFarmApiError(mutationError, t('deleteFailed')));
          }
        });
      })();
    });
  }, [t, tCommon, statusLabel, dateLocale, confirm, deleteMutation, perms]);

  const { table } = useDataTable<AccountOut>({
    data: filteredData,
    columns
  });

  return (
    <div className='space-y-5'>
      {deepLinkedAccount ? (
        <AccountLoginDialog
          key={deepLinkedAccount.id}
          account={deepLinkedAccount}
          canUpdate={perms.canUpdate}
          open={!deepLinkDismissed}
          onOpenChange={(nextOpen) => {
            if (!nextOpen) setDeepLinkDismissed(true);
          }}
          hideTrigger
        />
      ) : null}
      <div className='grid gap-3 sm:grid-cols-2 xl:grid-cols-4'>
        <AccountMetricCard
          label={t('metricTotal')}
          value={stats.total}
          hint={t('metricTotalHint')}
        />
        <AccountMetricCard
          label={t('metricReady')}
          value={stats.ready}
          hint={t('metricReadyHint')}
        />
        <AccountMetricCard
          label={t('metricUnassigned')}
          value={stats.unassigned}
          hint={t('metricUnassignedHint')}
        />
        <AccountMetricCard
          label={t('metricNeedsReview')}
          value={stats.needsReview}
          hint={t('metricNeedsReviewHint')}
          tone={stats.needsReview > 0 ? 'warning' : 'neutral'}
        />
      </div>

      {isLoading || error ? (
        <div className='rounded-md border bg-background p-4'>
          {isLoading && (
            <p className='text-sm text-muted-foreground'>{t('loading')}</p>
          )}
          {error && (
            <p className='text-sm text-destructive'>{t('loadError')}</p>
          )}
        </div>
      ) : null}

      <div className='rounded-lg border bg-background p-4 shadow-sm'>
        <div className='flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between'>
          <div>
            <div className='flex items-center gap-2 text-sm font-medium'>
              <Users size={16} />
              <span>{t('inventoryTitle')}</span>
            </div>
            <p className='mt-1 text-xs text-muted-foreground'>
              {t('inventoryDescription')}
            </p>
          </div>
          {data.length > 0 && perms.canCreate ? (
            <div className='flex flex-wrap gap-2'>
              <ImportAccountsDialog />
              <CreateAccountDialog />
            </div>
          ) : null}
        </div>

        <div className='mt-4 rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground'>
          <p className='font-medium text-foreground'>{t('actionHelpTitle')}</p>
          <ul className='mt-2 grid gap-1 sm:grid-cols-3'>
            <li>{t('actionHelpLogin')}</li>
            <li>{t('actionHelpLink')}</li>
            <li>{t('actionHelpMore')}</li>
          </ul>
        </div>

        <div className='mt-4 grid gap-3 lg:grid-cols-[minmax(220px,1fr)_auto] lg:items-center'>
          <div className='relative'>
            <Search className='pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t('searchPlaceholder')}
              className='pl-9'
            />
          </div>
          <Select
            value={statusFilter}
            onValueChange={(value) =>
              setStatusFilter(value as AccountStateKey | 'all')
            }
          >
            <SelectTrigger
              className='w-full lg:w-[220px]'
              aria-label={t('statusFilterLabel')}
            >
              <div className='flex min-w-0 items-center gap-2'>
                <Filter className='size-4 shrink-0 text-muted-foreground' />
                <SelectValue placeholder={t('filterAll')} />
              </div>
            </SelectTrigger>
            <SelectContent align='end'>
              {STATUS_FILTERS.map((status) => (
                <SelectItem key={status} value={status}>
                  {status === 'all' ? t('filterAll') : statusLabel[status]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {data.length === 0 && !isLoading ? (
        <Can
          object='accounts'
          action='create'
          fallback={
            <CoreEmptyState
              icon={Users}
              title={t('emptyTitle')}
              description={t('emptyDescription')}
              readOnlyHint={tEmpty('readOnlyHint')}
              trackingKey='accounts-empty-readonly'
            />
          }
        >
          <CoreEmptyState
            icon={Users}
            title={t('emptyTitle')}
            description={t('emptyDescription')}
            trackingKey='accounts-empty'
            action={
              <div className='flex flex-wrap justify-center gap-2'>
                <ImportAccountsDialog />
                <CreateAccountDialog />
              </div>
            }
          />
        </Can>
      ) : (
        <DataTable table={table} total={filteredData.length} />
      )}
    </div>
  );
}

function AccountMetricCard({
  label,
  value,
  hint,
  tone = 'neutral'
}: {
  label: string;
  value: number;
  hint: string;
  tone?: 'neutral' | 'warning';
}) {
  return (
    <div
      className={cn(
        'rounded-lg border bg-background p-4 shadow-sm',
        tone === 'warning' && 'border-amber-500/40 bg-amber-500/5'
      )}
    >
      <p className='text-xs font-medium uppercase tracking-wide text-muted-foreground'>
        {label}
      </p>
      <p className='mt-2 text-2xl font-semibold tabular-nums'>{value}</p>
      <p className='mt-1 text-xs text-muted-foreground'>{hint}</p>
    </div>
  );
}
