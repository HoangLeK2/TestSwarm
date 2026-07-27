'use client';

import { useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import {
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Search,
  Users,
  X
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
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
import { cn } from '@/lib/utils';
import { useGroupCatalog } from '../hooks/use-group-catalog';
import {
  getGroupMemberCount,
  getGroupPrivacy,
  isGroupStale
} from '../lib/group-catalog';
import type { ExternalEntityCatalogItem } from '../services/api';

const PAGE_SIZE = 25;

function GroupTable({
  items,
  now
}: {
  items: ExternalEntityCatalogItem[];
  now: Date;
}) {
  const t = useTranslations('externalEntityFeature.groups');
  const locale = useLocale();

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t('columnGroup')}</TableHead>
          <TableHead>{t('columnPrivacy')}</TableHead>
          <TableHead>{t('columnMembers')}</TableHead>
          <TableHead>{t('columnLastSeen')}</TableHead>
          <TableHead>{t('columnStatus')}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => {
          const privacy = getGroupPrivacy(item);
          const memberCount = getGroupMemberCount(item);
          const stale = isGroupStale(item, now);
          const statusLabel =
            item.status === 'candidate'
              ? t('statusCandidate')
              : item.status === 'active'
                ? t('statusActive')
                : item.status === 'resolved'
                  ? t('statusResolved')
                  : item.status;
          return (
            <TableRow key={item.id}>
              <TableCell className='max-w-[320px]'>
                <div className='flex min-w-0 items-center gap-3'>
                  <div className='flex size-9 shrink-0 items-center justify-center rounded-full bg-blue-500/10 text-blue-600 dark:text-blue-300'>
                    <Users className='size-4' />
                  </div>
                  <div className='min-w-0'>
                    <p className='truncate font-medium text-foreground'>
                      {item.display_name}
                    </p>
                    <p className='truncate text-xs text-muted-foreground'>
                      {item.identity_confidence === 'name_only'
                        ? t('identityNameOnly')
                        : item.external_id || item.identity_confidence}
                    </p>
                  </div>
                </div>
              </TableCell>
              <TableCell>
                {privacy === 'public'
                  ? t('privacyPublic')
                  : privacy === 'private'
                    ? t('privacyPrivate')
                    : t('unknown')}
              </TableCell>
              <TableCell className='tabular-nums'>
                {memberCount == null
                  ? t('unknown')
                  : memberCount.toLocaleString(locale)}
              </TableCell>
              <TableCell>
                <div className='flex flex-col items-start gap-1'>
                  <span>
                    {new Date(item.last_seen_at).toLocaleString(locale, {
                      dateStyle: 'short',
                      timeStyle: 'short'
                    })}
                  </span>
                  {stale ? (
                    <Badge
                      variant='outline'
                      className='border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300'
                    >
                      {t('stale')}
                    </Badge>
                  ) : null}
                </div>
              </TableCell>
              <TableCell>
                <Badge variant='outline'>{statusLabel}</Badge>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export function GroupCatalogView() {
  const t = useTranslations('externalEntityFeature.groups');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [page, setPage] = useState(0);
  const query = useGroupCatalog({
    search: search || undefined,
    status: status === 'all' ? undefined : status,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE
  });
  const total = query.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const now = new Date();

  const applySearch = () => {
    setPage(0);
    setSearch(searchInput.trim());
  };

  const clearFilters = () => {
    setSearchInput('');
    setSearch('');
    setStatus('all');
    setPage(0);
  };

  return (
    <div className='space-y-5'>
      <div className='overflow-hidden rounded-2xl border border-border/60 bg-card shadow-sm'>
        <div className='flex flex-wrap items-center justify-between gap-3 border-b border-border/60 bg-gradient-to-b from-muted/40 to-transparent px-5 py-4'>
          <div>
            <p className='text-base font-semibold leading-tight text-foreground'>
              {t('title')}
            </p>
            <p className='mt-1 text-xs text-muted-foreground'>
              {t('subtitle')}
            </p>
          </div>
          <Badge
            variant='secondary'
            className='h-8 gap-1.5 rounded-full px-3 text-xs font-semibold tabular-nums'
          >
            <Users className='size-3.5' />
            {t('count', { count: total })}
          </Badge>
        </div>

        <div className='flex flex-wrap items-center gap-2 border-b border-border/60 bg-muted/10 px-5 py-4'>
          <div className='relative min-w-[260px] flex-1'>
            <Search className='pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
            <Input
              className='h-10 pl-9'
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') applySearch();
              }}
              placeholder={t('searchPlaceholder')}
              aria-label={t('searchAria')}
            />
          </div>
          <Select
            value={status}
            onValueChange={(value) => {
              setStatus(value);
              setPage(0);
            }}
          >
            <SelectTrigger className='h-10 w-[170px]'>
              <SelectValue placeholder={t('statusAll')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value='all'>{t('statusAll')}</SelectItem>
              <SelectItem value='candidate'>{t('statusCandidate')}</SelectItem>
              <SelectItem value='active'>{t('statusActive')}</SelectItem>
              <SelectItem value='resolved'>{t('statusResolved')}</SelectItem>
            </SelectContent>
          </Select>
          <Button className='h-10' onClick={applySearch}>
            {t('filter')}
          </Button>
          {(search || status !== 'all') && (
            <Button variant='ghost' className='h-10' onClick={clearFilters}>
              <X className='mr-1.5 size-4' />
              {t('clear')}
            </Button>
          )}
          <Button
            variant='outline'
            size='icon'
            className='size-10'
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
            title={t('refresh')}
            aria-label={t('refresh')}
          >
            <RefreshCw
              className={cn('size-4', query.isFetching && 'animate-spin')}
            />
          </Button>
        </div>

        <div className='p-5'>
          {query.isError || query.organizationError ? (
            <div
              role='alert'
              className='rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive'
            >
              {t('loadError')}
            </div>
          ) : query.isLoading || query.organizationLoading ? (
            <div className='space-y-2'>
              {Array.from({ length: 6 }).map((_, index) => (
                <div
                  key={index}
                  className='h-14 animate-pulse rounded-lg bg-muted/60'
                />
              ))}
            </div>
          ) : (query.data?.items.length ?? 0) === 0 ? (
            <div className='flex min-h-52 flex-col items-center justify-center rounded-xl border border-dashed border-border/70 bg-muted/20 px-6 text-center'>
              <Users className='mb-3 size-9 text-muted-foreground/60' />
              <p className='font-medium'>{t('emptyTitle')}</p>
              <p className='mt-1 max-w-lg text-sm text-muted-foreground'>
                {search || status !== 'all'
                  ? t('emptyFiltered')
                  : t('emptyDescription')}
              </p>
            </div>
          ) : (
            <GroupTable items={query.data?.items ?? []} now={now} />
          )}
        </div>

        {!query.isLoading && total > 0 ? (
          <div className='flex items-center justify-between border-t border-border/60 bg-muted/10 px-5 py-3'>
            <p className='text-xs text-muted-foreground'>
              {t('pageCount', {
                from: page * PAGE_SIZE + 1,
                to: Math.min((page + 1) * PAGE_SIZE, total),
                total
              })}
            </p>
            <div className='flex items-center gap-2'>
              <Button
                size='sm'
                variant='outline'
                disabled={page === 0}
                onClick={() => setPage((value) => Math.max(0, value - 1))}
              >
                <ChevronLeft className='mr-1 size-4' />
                {t('previous')}
              </Button>
              <span className='text-xs font-medium tabular-nums'>
                {page + 1} / {totalPages}
              </span>
              <Button
                size='sm'
                variant='outline'
                disabled={page + 1 >= totalPages}
                onClick={() => setPage((value) => value + 1)}
              >
                {t('next')}
                <ChevronRight className='ml-1 size-4' />
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
