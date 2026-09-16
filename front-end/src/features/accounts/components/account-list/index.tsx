'use client';

import { useMemo } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { enUS, vi } from 'date-fns/locale';
import { Users } from 'lucide-react';
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

export function AccountList() {
  const t = useTranslations('accountsFeature.list');
  const tEmpty = useTranslations('coreEmptyState');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  const dateLocale = locale === 'vi' ? vi : enUS;
  const confirm = useConfirm();
  // Không truyền limit thì server mặc định 50 và cắt im lặng.
  const {
    data: accounts,
    isLoading,
    error
  } = useAccounts({ limit: ACCOUNTS_PAGE_LIMIT });
  const deleteMutation = useDeleteAccount();
  const perms = useResourcePermissions('accounts');

  const data: AccountOut[] = accounts ?? [];

  const columns = useMemo(() => {
    const statusLabel: Record<AccountStateKey, string> = {
      unassigned: t('statusUnassigned'),
      assigned: t('statusAssigned'),
      active: t('statusActive'),
      suspended: t('statusVerifying'),
      banned: t('statusBanned'),
      retired: t('statusRetired')
    };

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
        deleteMutation.mutate(account.id);
      })();
    });
  }, [t, tCommon, dateLocale, confirm, deleteMutation, perms]);

  const { table } = useDataTable<AccountOut>({
    data,
    columns
  });

  return (
    <div className='space-y-6'>
      {isLoading || error ? (
        <div>
          {isLoading && (
            <p className='text-sm text-muted-foreground'>{t('loading')}</p>
          )}
          {error && (
            <p className='text-sm text-destructive'>{t('loadError')}</p>
          )}
        </div>
      ) : null}

      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div className='flex items-center gap-2 text-sm text-muted-foreground'>
          <Users size={16} />
          <span>
            {data.length} {t('countLabel')}
          </span>
        </div>
        {data.length > 0 && perms.canCreate ? (
          <div className='flex flex-wrap gap-2'>
            <ImportAccountsDialog />
            <CreateAccountDialog />
          </div>
        ) : null}
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
        <DataTable table={table} total={data.length} />
      )}
    </div>
  );
}
