'use client';

import { useMemo } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { enUS, vi } from 'date-fns/locale';
import { Users } from 'lucide-react';
import { useAccounts, useDeleteAccount } from '../../hooks/use-accounts';
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
  const { data: accounts, isLoading, error } = useAccounts();
  const deleteMutation = useDeleteAccount();
  const perms = useResourcePermissions('accounts');

  const data: AccountOut[] = accounts ?? [];

  const columns = useMemo(() => {
    const statusLabel: Record<AccountStateKey, string> = {
      active: t('statusActive'),
      cooldown: t('statusCooldown'),
      suspended: t('statusSuspended'),
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
    columns,
    pageCount: 1
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
        <div className='flex flex-wrap gap-2'>
          {perms.canCreate ? <ImportAccountsDialog /> : null}
          {perms.canCreate ? <CreateAccountDialog /> : null}
        </div>
      </div>

      {data.length === 0 && !isLoading ? (
        <Can
          object='accounts'
          action='create'
          fallback={
            <CoreEmptyState
              icon={Users}
              title={tEmpty('accounts.title')}
              description={tEmpty('accounts.description')}
              readOnlyHint={tEmpty('readOnlyHint')}
              trackingKey='accounts-empty-readonly'
            />
          }
        >
          <div className='space-y-4'>
            <CoreEmptyState
              icon={Users}
              title={tEmpty('accounts.title')}
              description={tEmpty('accounts.description')}
              trackingKey='accounts-empty'
            />
            <div className='flex justify-center'>
              <CreateAccountDialog />
            </div>
          </div>
        </Can>
      ) : (
        <DataTable table={table} />
      )}
    </div>
  );
}
