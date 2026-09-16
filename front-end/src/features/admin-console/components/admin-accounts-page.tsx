'use client';

import { useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { AtSign } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { Badge } from '@/components/ui/badge';
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
  StatusBadge
} from './admin-shared';
import { useAdminWorkspaceScope } from '../hooks/use-admin-workspace-scope';
import { adminApi, formatAdminApiError } from '../services/admin-api';

const ALL = '__all__';

function dateLabel(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '-';
}

export function AdminAccountsPage() {
  const t = useTranslations('adminConsole.accounts');
  const scope = useAdminWorkspaceScope();
  const [search, setSearch] = useState('');
  const [platform, setPlatform] = useState(ALL);
  const [state, setState] = useState(ALL);
  const [offset, setOffset] = useState(0);

  const params = useMemo(
    () => ({
      search: search || undefined,
      platform: platform === ALL ? undefined : platform,
      state: state === ALL ? undefined : state,
      workspaceId: scope.scopedWorkspaceId,
      offset,
      limit: ADMIN_PAGE_SIZE
    }),
    [offset, platform, scope.scopedWorkspaceId, search, state]
  );

  const accounts = useQuery({
    queryKey: ['admin-accounts', params],
    queryFn: () => adminApi.listAccounts(params)
  });

  return (
    <div className='min-h-full bg-muted/20'>
      <AdminPageHeader title={t('title')} description={t('description')} />
      <div className='space-y-4 p-4 md:p-6'>
        <div className='grid gap-3 rounded-md border bg-background p-3 lg:grid-cols-[minmax(220px,1fr)_260px_170px_170px]'>
          <SearchField
            value={search}
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
            placeholder={t('searchPlaceholder')}
          />
          <AdminWorkspaceScopeSelect
            value={scope.workspaceId}
            onChange={(value) => {
              scope.setWorkspaceId(value);
              setOffset(0);
            }}
            workspaces={scope.workspaces}
            allowGlobalScope={scope.allowGlobalScope}
            workspaceLabel={t('filters.workspace')}
            allWorkspacesLabel={t('filters.allWorkspaces')}
          />
          <Select
            value={platform}
            onValueChange={(value) => {
              setPlatform(value);
              setOffset(0);
            }}
          >
            <SelectTrigger className='w-full'>
              <SelectValue placeholder={t('filters.platform')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('filters.allPlatforms')}</SelectItem>
              <SelectItem value='facebook'>Facebook</SelectItem>
              <SelectItem value='tiktok'>TikTok</SelectItem>
              <SelectItem value='instagram'>Instagram</SelectItem>
              <SelectItem value='youtube'>YouTube</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={state}
            onValueChange={(value) => {
              setState(value);
              setOffset(0);
            }}
          >
            <SelectTrigger className='w-full'>
              <SelectValue placeholder={t('filters.state')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('filters.allStates')}</SelectItem>
              <SelectItem value='unassigned'>
                {t('states.unassigned')}
              </SelectItem>
              <SelectItem value='assigned'>{t('states.assigned')}</SelectItem>
              <SelectItem value='active'>{t('states.active')}</SelectItem>
              <SelectItem value='suspended'>{t('states.suspended')}</SelectItem>
              <SelectItem value='banned'>{t('states.banned')}</SelectItem>
              <SelectItem value='retired'>{t('states.retired')}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {accounts.isError ? (
          <AdminErrorState
            message={formatAdminApiError(accounts.error)}
            onRetry={() => void accounts.refetch()}
          />
        ) : null}

        <div className='overflow-hidden rounded-md border bg-background'>
          <div className='overflow-x-auto'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('table.workspace')}</TableHead>
                  <TableHead>{t('table.account')}</TableHead>
                  <TableHead>{t('table.platform')}</TableHead>
                  <TableHead>{t('table.state')}</TableHead>
                  <TableHead>{t('table.lastUsed')}</TableHead>
                  <TableHead>{t('table.updated')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {accounts.isLoading ? <AdminTableSkeleton columns={6} /> : null}
                {accounts.data?.items.map((account) => (
                  <TableRow key={account.id}>
                    <TableCell>
                      <div className='min-w-[180px]'>
                        <p className='font-medium'>
                          {account.workspaceName || t('table.unknownWorkspace')}
                        </p>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className='min-w-[220px]'>
                        <p className='font-medium'>{account.username}</p>
                        <p className='flex items-center gap-1 text-xs text-muted-foreground'>
                          <AtSign className='size-3' />
                          {account.display_name || account.id}
                        </p>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant='outline' className='capitalize'>
                        {account.platform}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <StatusBadge value={account.state} />
                    </TableCell>
                    <TableCell className='text-sm text-muted-foreground'>
                      {dateLabel(account.last_used_at)}
                    </TableCell>
                    <TableCell className='text-sm text-muted-foreground'>
                      {dateLabel(account.updated_at)}
                    </TableCell>
                  </TableRow>
                ))}
                {!accounts.isLoading && accounts.data?.items.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={6}
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
            total={accounts.data?.total ?? 0}
            onOffsetChange={setOffset}
          />
        </div>
      </div>
    </div>
  );
}
