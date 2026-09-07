'use client';

import { useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { useQuery } from '@tanstack/react-query';
import { Input } from '@/components/ui/input';
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
  SearchField
} from './admin-shared';
import { adminApi, formatAdminApiError } from '../services/admin-api';

function dateLabel(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '-';
}

function safeDetails(details?: Record<string, unknown> | null) {
  if (!details) return '-';
  const redacted = Object.fromEntries(
    Object.entries(details).filter(([key]) => {
      const normalized = key.toLowerCase();
      return (
        !normalized.includes('password') &&
        !normalized.includes('token') &&
        !normalized.includes('secret')
      );
    })
  );
  return JSON.stringify(redacted);
}

export function AdminAuditPage() {
  const t = useTranslations('adminConsole.audit');
  const [action, setAction] = useState('');
  const [resourceType, setResourceType] = useState('');
  const [actor, setActor] = useState('');
  const [offset, setOffset] = useState(0);
  const params = useMemo(
    () => ({
      action: action || undefined,
      resourceType: resourceType || undefined,
      actor: actor || undefined,
      offset,
      limit: ADMIN_PAGE_SIZE
    }),
    [action, actor, offset, resourceType]
  );

  const audit = useQuery({
    queryKey: ['admin-audit-log', params],
    queryFn: () => adminApi.auditLog(params),
    refetchInterval: 30_000
  });

  return (
    <div className='min-h-full bg-muted/20'>
      <AdminPageHeader
        title={t('title')}
        description={t('legacyDescription')}
      />
      <div className='space-y-4 p-4 md:p-6'>
        <div className='grid gap-3 rounded-md border bg-background p-3 lg:grid-cols-[minmax(220px,1fr)_220px_220px]'>
          <SearchField
            value={action}
            onChange={(value) => {
              setAction(value);
              setOffset(0);
            }}
            placeholder={t('filters.action')}
          />
          <Input
            value={resourceType}
            onChange={(event) => {
              setResourceType(event.target.value);
              setOffset(0);
            }}
            placeholder={t('filters.resourceType')}
          />
          <Input
            value={actor}
            onChange={(event) => {
              setActor(event.target.value);
              setOffset(0);
            }}
            placeholder={t('filters.actor')}
          />
        </div>

        {audit.isError ? (
          <AdminErrorState
            message={formatAdminApiError(audit.error)}
            onRetry={() => void audit.refetch()}
          />
        ) : null}

        <div className='overflow-hidden rounded-md border bg-background'>
          <div className='overflow-x-auto'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('table.time')}</TableHead>
                  <TableHead>{t('table.actor')}</TableHead>
                  <TableHead>{t('table.action')}</TableHead>
                  <TableHead>{t('table.resource')}</TableHead>
                  <TableHead>{t('table.workspace')}</TableHead>
                  <TableHead>{t('table.details')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {audit.isLoading ? <AdminTableSkeleton columns={6} /> : null}
                {audit.data?.activities.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className='whitespace-nowrap text-sm text-muted-foreground'>
                      {dateLabel(row.created_at)}
                    </TableCell>
                    <TableCell className='font-mono text-xs'>
                      {row.user_id || '-'}
                    </TableCell>
                    <TableCell className='font-medium'>{row.action}</TableCell>
                    <TableCell className='font-mono text-xs'>
                      {row.entity_type || '-'}:{row.entity_id || '-'}
                    </TableCell>
                    <TableCell className='font-mono text-xs'>
                      {row.org_id || '-'}
                    </TableCell>
                    <TableCell className='max-w-[360px] truncate font-mono text-xs text-muted-foreground'>
                      {safeDetails(row.details)}
                    </TableCell>
                  </TableRow>
                ))}
                {!audit.isLoading && audit.data?.activities.length === 0 ? (
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
            total={audit.data?.total ?? 0}
            onOffsetChange={setOffset}
          />
        </div>
      </div>
    </div>
  );
}
