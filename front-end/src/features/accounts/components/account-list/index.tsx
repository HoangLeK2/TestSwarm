'use client';

import { useMemo } from 'react';
import { useTranslations } from 'next-intl';
import { Users } from 'lucide-react';
import {
  useAccounts,
  useDeleteAccount,
  useUpdateAccountStatus
} from '../../hooks/use-accounts';
import type { AccountOut } from '../../services/api';
import { DataTable } from '@/components/ui/table/data-table';
import { useDataTable } from '@/hooks/use-data-table';
import { CreateAccountDialog } from '../create-account-dialog';
import { ImportAccountsDialog } from '../import-accounts-dialog';
import { getAccountColumns } from './columns';
import { useConfirm } from '@/providers/modal-provider';

export function AccountList() {
  const t = useTranslations('accountsFeature.list');
  const tCommon = useTranslations('common');
  const confirm = useConfirm();
  const { data: accounts, isLoading, error } = useAccounts();
  const deleteMutation = useDeleteAccount();
  const statusMutation = useUpdateAccountStatus();

  const data: AccountOut[] = accounts ?? [];

  const columns = useMemo(
    () =>
      getAccountColumns(
        t,
        (account) => {
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
        },
        (account, status) => {
          statusMutation.mutate({ accountId: account.id, status });
        }
      ),
    [t, tCommon, confirm, deleteMutation, statusMutation]
  );

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
          {error && <p className='text-sm text-destructive'>{t('loadError')}</p>}
        </div>
      ) : (
        <>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <p className='text-muted-foreground'>
              <span className='font-medium text-foreground'>
                {accounts?.length ?? 0}
              </span>{' '}
              {t('countLabel')}
            </p>
            <div className='flex gap-2'>
              <ImportAccountsDialog />
              <CreateAccountDialog />
            </div>
          </div>

          {!accounts?.length && (
            <div className='rounded-xl border border-dashed border-border bg-muted/20 p-16 text-center'>
              <Users className='mx-auto mb-4 size-12 text-muted-foreground/80' />
              <p className='text-sm font-medium text-foreground'>
                {t('emptyTitle')}
              </p>
              <p className='mt-1 text-sm text-muted-foreground'>
                {t('emptyDescription')}
              </p>
              <div className='mt-6 flex justify-center gap-2'>
                <ImportAccountsDialog />
                <CreateAccountDialog />
              </div>
            </div>
          )}

          {accounts?.length ? (
            <DataTable table={table} total={accounts.length} />
          ) : null}
        </>
      )}
    </div>
  );
}
