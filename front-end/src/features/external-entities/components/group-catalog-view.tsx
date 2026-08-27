'use client';

import { useEffect, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { Filter, RefreshCw, Search, Users, X } from 'lucide-react';

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
import { TablePaginationControls } from '@/components/ui/table/data-table-pagination';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { useDebouncedCallback } from '@/hooks/use-debounced-callback';
import { cn } from '@/lib/utils';
import { useGroupCatalog } from '../hooks/use-group-catalog';
import {
  getGroupMemberCount,
  getGroupPrivacy,
  isGroupStale
} from '../lib/group-catalog';
import type { ExternalEntityCatalogItem } from '../services/api';

const DEFAULT_PAGE_SIZE = 25;

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
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const updateSearch = useDebouncedCallback((value: string) => {
    setPage(0);
    setSearch(value.trim());
  }, 300);
  const query = useGroupCatalog({
    search: search || undefined,
    status: status === 'all' ? undefined : status,
    limit: pageSize,
    offset: page * pageSize
  });
  const total = query.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const now = new Date();

  useEffect(() => {
    updateSearch(searchInput);
  }, [searchInput, updateSearch]);

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

        <div className='grid gap-2 border-b border-border/60 bg-muted/10 px-5 py-4 sm:grid-cols-[minmax(260px,1fr)_190px_auto]'>
          <div className='relative min-w-0'>
            <Search className='pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
            <Input
              className='h-10 pl-9'
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
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
            <SelectTrigger className='h-10 w-full'>
              <Filter className='size-4' />
              <SelectValue placeholder={t('statusAll')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value='all'>{t('statusAll')}</SelectItem>
              <SelectItem value='candidate'>{t('statusCandidate')}</SelectItem>
              <SelectItem value='active'>{t('statusActive')}</SelectItem>
              <SelectItem value='resolved'>{t('statusResolved')}</SelectItem>
            </SelectContent>
          </Select>
          <div className='flex justify-end gap-2'>
            {(search || status !== 'all') && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant='outline'
                    size='icon'
                    className='size-10'
                    onClick={clearFilters}
                    aria-label={t('clear')}
                  >
                    <X className='size-4' />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('clear')}</TooltipContent>
              </Tooltip>
            )}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant='outline'
                  size='icon'
                  className='size-10'
                  onClick={() => void query.refetch()}
                  disabled={query.isFetching}
                  aria-label={t('refresh')}
                >
                  <RefreshCw
                    className={cn('size-4', query.isFetching && 'animate-spin')}
                  />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t('refresh')}</TooltipContent>
            </Tooltip>
          </div>
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
          <div className='border-t border-border/60 bg-muted/10 px-5 py-3'>
            <TablePaginationControls
              pageIndex={page}
              pageCount={totalPages}
              pageSize={pageSize}
              pageSizeOptions={[10, 25, 50, 100]}
              total={total}
              onPageIndexChange={setPage}
              onPageSizeChange={(value) => {
                setPage(0);
                setPageSize(value);
              }}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
