'use client';

import { useMemo, useState } from 'react';
import { useFormatter, useTranslations } from 'next-intl';
import { Building2, Search } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useOrganizationsPaginated } from '../hooks/use-organizations';
import { formatOrgDisplayName } from '../utils/org-name';
import { useUser } from '@/features/auth';
import { isSuperadminRole } from '@/lib/nav-access';

const PAGE_SIZE = 20;

export function OrganizationListPage() {
  const t = useTranslations('organization.listing');
  const tOrg = useTranslations('organization');
  const format = useFormatter();
  const { user, isLoading: authLoading } = useUser();
  const canAccess = isSuperadminRole(user?.role);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');

  const { data, isLoading, isFetching, error } = useOrganizationsPaginated(
    page,
    PAGE_SIZE,
    search,
    { enabled: !authLoading && canAccess }
  );

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const noNameFallback = tOrg('noName');

  const rows = useMemo(
    () =>
      items.map((org) => ({
        ...org,
        displayName: formatOrgDisplayName(org.businessName, noNameFallback)
      })),
    [items, noNameFallback]
  );

  const applySearch = () => {
    setPage(0);
    setSearch(searchInput.trim());
  };

  if (authLoading || !canAccess) {
    return null;
  }

  return (
    <div className='mx-auto w-full max-w-5xl space-y-6 p-4 md:p-6'>
      <div className='flex items-start gap-3'>
        <Building2 className='mt-0.5 size-5 shrink-0 text-muted-foreground' />
        <div>
          <h1 className='text-xl font-semibold tracking-tight'>{t('title')}</h1>
          <p className='text-sm text-muted-foreground'>{t('description')}</p>
        </div>
      </div>

      <div className='flex flex-col gap-3 sm:flex-row sm:items-center'>
        <div className='relative flex-1'>
          <Search className='absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') applySearch();
            }}
            placeholder={t('searchPlaceholder')}
            className='pl-9'
          />
        </div>
        <Button type='button' variant='secondary' onClick={applySearch}>
          {t('search')}
        </Button>
      </div>

      {isLoading ? (
        <div className='space-y-2'>
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className='h-14 w-full rounded-lg' />
          ))}
        </div>
      ) : error ? (
        <p className='text-sm text-destructive'>{tOrg('messages.loadError')}</p>
      ) : rows.length === 0 ? (
        <p className='text-sm text-muted-foreground'>
          {t('noOrganizationsFound')}
        </p>
      ) : (
        <div className='overflow-hidden rounded-xl border border-border'>
          <div className='divide-y divide-border'>
            {rows.map((org) => (
              <div
                key={org.id}
                className='flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between'
              >
                <div className='min-w-0'>
                  <p className='truncate font-medium'>{org.displayName}</p>
                  <p className='truncate text-sm text-muted-foreground'>
                    {org.businessEmail || '—'}
                  </p>
                </div>
                <div className='flex shrink-0 items-center gap-2 text-xs text-muted-foreground'>
                  {org.status ? (
                    <Badge variant='outline'>{org.status}</Badge>
                  ) : null}
                  <span>
                    {format.dateTime(new Date(org.created_at), {
                      dateStyle: 'medium'
                    })}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {total > 0 ? (
        <div className='flex flex-col items-center justify-between gap-3 sm:flex-row'>
          <p className='text-sm text-muted-foreground'>
            {t('showing', {
              from: total === 0 ? 0 : page * PAGE_SIZE + 1,
              to: Math.min((page + 1) * PAGE_SIZE, total),
              total
            })}
          </p>
          <div className='flex items-center gap-2'>
            <Button
              type='button'
              variant='outline'
              size='sm'
              disabled={page <= 0 || isFetching}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              {t('prev')}
            </Button>
            <span className='text-sm text-muted-foreground'>
              {t('pageOf', { current: page + 1, total: totalPages })}
            </span>
            <Button
              type='button'
              variant='outline'
              size='sm'
              disabled={page + 1 >= totalPages || isFetching}
              onClick={() => setPage((p) => p + 1)}
            >
              {t('next')}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
