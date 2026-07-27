'use client';

import { useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { useRouter } from '@/i18n/navigation';
import Link from 'next/link';
import { ROUTES } from '@/config/routes';
import {
  Search,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Database,
  TrendingUp,
  Smartphone,
  FileText,
  MessageCircle,
  Newspaper,
  Download,
  ChevronDown,
  X,
  Filter,
  Hash
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { CoreEmptyState } from '@/components/core-empty-state';
import { ContentExportDialog } from './content-export-panel';
import { useContent, useContentStats } from '../hooks/use-content';
import {
  contentApi,
  type ContentItem,
  type ExportFormat
} from '../services/api';
import { ContentTable } from './content-table';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { useCampaigns } from '@/features/campaigns/hooks/use-campaigns';

// ── Stats bar ────────────────────────────────────────────────────────────────

function StatsBar() {
  const t = useTranslations('contentFeature.list');
  const locale = useLocale();
  const { stats, loading } = useContentStats();
  if (loading && !stats) return <StatsBarSkeleton />;
  if (!stats) return null;
  return (
    <div className='grid grid-cols-2 gap-3 sm:grid-cols-4'>
      <StatCard
        icon={<Database className='size-5' />}
        label={t('statsTotalRecords')}
        value={stats.total_items.toLocaleString(locale)}
        tint='primary'
      />
      <StatCard
        icon={<TrendingUp className='size-5' />}
        label={t('statsPlatforms')}
        value={Object.keys(stats.by_platform).length.toString()}
        tint='emerald'
      />
      <StatCard
        icon={<FileText className='size-5' />}
        label={t('statsCollections')}
        value={Object.keys(stats.by_collection).length.toString()}
        tint='blue'
      />
      <StatCard
        icon={<Smartphone className='size-5' />}
        label={t('statsLatestScrape')}
        value={
          stats.latest_extraction
            ? new Date(stats.latest_extraction).toLocaleString(locale, {
                dateStyle: 'short',
                timeStyle: 'short'
              })
            : '–'
        }
        tint='violet'
      />
    </div>
  );
}

function StatsBarSkeleton() {
  return (
    <div className='grid grid-cols-2 gap-3 sm:grid-cols-4'>
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className='h-[88px] animate-pulse rounded-xl border border-border/60 bg-muted/40'
        />
      ))}
    </div>
  );
}

type StatTint = 'primary' | 'emerald' | 'blue' | 'violet';

const STAT_TINTS: Record<
  StatTint,
  { bubble: string; icon: string; ring: string }
> = {
  primary: {
    bubble: 'bg-primary/10',
    icon: 'text-primary',
    ring: 'ring-primary/10'
  },
  emerald: {
    bubble: 'bg-emerald-500/10',
    icon: 'text-emerald-600 dark:text-emerald-400',
    ring: 'ring-emerald-500/10'
  },
  blue: {
    bubble: 'bg-blue-500/10',
    icon: 'text-blue-600 dark:text-blue-400',
    ring: 'ring-blue-500/10'
  },
  violet: {
    bubble: 'bg-violet-500/10',
    icon: 'text-violet-600 dark:text-violet-400',
    ring: 'ring-violet-500/10'
  }
};

function StatCard({
  icon,
  label,
  value,
  tint
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tint: StatTint;
}) {
  const s = STAT_TINTS[tint];
  return (
    <div
      className={cn(
        'group relative overflow-hidden rounded-xl border border-border/60 bg-card p-4 shadow-sm ring-1 ring-transparent transition-all hover:-translate-y-0.5 hover:shadow-md',
        s.ring
      )}
    >
      <div className='flex items-start gap-3'>
        <div
          className={cn(
            'flex size-10 shrink-0 items-center justify-center rounded-lg',
            s.bubble,
            s.icon
          )}
        >
          {icon}
        </div>
        <div className='min-w-0 flex-1'>
          <p className='truncate text-xs font-medium uppercase tracking-wide text-muted-foreground'>
            {label}
          </p>
          <p className='mt-1 truncate text-2xl font-bold tabular-nums leading-tight text-foreground'>
            {value}
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Filters ──────────────────────────────────────────────────────────────────

type ContentDatasetType = 'fb_post' | 'fb_comment';

const DEFAULT_CONTENT_TYPE: ContentDatasetType = 'fb_post';

interface FiltersProps {
  search: string;
  onSearchChange: (v: string) => void;
  campaignId: string;
  onCampaignIdChange: (v: string) => void;
  collection: string;
  onCollectionChange: (v: string) => void;
  platform: string;
  onPlatformChange: (v: string) => void;
  contentType: ContentDatasetType;
  onContentTypeChange: (v: ContentDatasetType) => void;
  onRefresh: () => void;
  onApply: () => void;
  onClear: () => void;
  loading: boolean;
  showContentTypeTabs: boolean;
}

function Filters({
  search,
  onSearchChange,
  campaignId,
  onCampaignIdChange,
  collection,
  onCollectionChange,
  platform,
  onPlatformChange,
  contentType,
  onContentTypeChange,
  onRefresh,
  onApply,
  onClear,
  loading,
  showContentTypeTabs
}: FiltersProps) {
  const t = useTranslations('contentFeature.list');
  const { data: campaigns = [], isLoading: loadingCampaigns } = useCampaigns();
  const { stats } = useContentStats();

  const contentTypeTabs = [
    {
      value: 'fb_post',
      label: t('tabPosts'),
      icon: <Newspaper className='size-3.5' />
    },
    {
      value: 'fb_comment',
      label: t('tabComments'),
      icon: <MessageCircle className='size-3.5' />
    }
  ] as const;

  const onKeyEnter = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') onApply();
  };
  const hasFilters = !!(
    search ||
    campaignId ||
    collection ||
    platform ||
    (showContentTypeTabs && contentType && contentType !== DEFAULT_CONTENT_TYPE)
  );

  const platformOptions = Object.keys(stats?.by_platform ?? {}).sort((a, b) =>
    a.localeCompare(b, 'vi')
  );
  const collectionOptions = Object.keys(stats?.by_collection ?? {}).sort(
    (a, b) => a.localeCompare(b, 'vi')
  );

  const selectedCampaign =
    campaignId && campaigns.length
      ? campaigns.find((c) => c.id === campaignId)
      : undefined;

  return (
    <div className='space-y-3'>
      {/* Tabs + actions */}
      <div className='flex flex-wrap items-center justify-between gap-2'>
        {showContentTypeTabs ? (
          <div className='inline-flex items-center gap-1 rounded-xl bg-muted/60 p-1 ring-1 ring-border/40'>
            {contentTypeTabs.map((tab) => {
              const active = contentType === tab.value;
              return (
                <button
                  key={tab.value}
                  type='button'
                  onClick={() => onContentTypeChange(tab.value)}
                  className={cn(
                    'inline-flex cursor-pointer items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all',
                    active
                      ? 'bg-background text-foreground shadow-sm ring-1 ring-border/60'
                      : 'text-muted-foreground hover:bg-background/60 hover:text-foreground'
                  )}
                  aria-pressed={active}
                >
                  {tab.icon}
                  {tab.label}
                </button>
              );
            })}
          </div>
        ) : (
          <span />
        )}

        <div className='flex items-center gap-2'>
          {hasFilters && (
            <Button
              size='sm'
              variant='ghost'
              className='h-9 gap-1.5 text-xs text-muted-foreground hover:text-foreground'
              onClick={onClear}
            >
              <X className='size-3.5' />
              {t('clearFilters')}
            </Button>
          )}
          <Button
            size='sm'
            variant='outline'
            className='h-9 gap-1.5 text-xs'
            onClick={onRefresh}
            disabled={loading}
            title={t('refreshTitle')}
          >
            <RefreshCw className={cn('size-3.5', loading && 'animate-spin')} />
            {t('refresh')}
          </Button>
        </div>
      </div>

      {/* Inputs row */}
      <div className='flex flex-wrap items-center gap-2'>
        <div className='relative min-w-[260px] flex-1'>
          <Search className='pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
          <Input
            className='h-10 pl-9 text-sm'
            placeholder={t('searchPlaceholder')}
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            onKeyDown={onKeyEnter}
            aria-label={t('searchAria')}
          />
        </div>
        <div className='relative min-w-[240px] max-w-full flex-[0_0_280px]'>
          <Hash className='pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
          <Select
            value={campaignId || '_all'}
            onValueChange={(v) => onCampaignIdChange(v === '_all' ? '' : v)}
            disabled={loadingCampaigns}
          >
            <SelectTrigger
              className='h-10 w-full min-w-0 overflow-hidden pl-9 text-sm'
              aria-label={t('filterCampaignAria')}
            >
              <SelectValue placeholder={t('filterCampaign')}>
                <span className='block w-full truncate'>
                  {campaignId
                    ? (selectedCampaign?.name ?? campaignId)
                    : t('filterCampaign')}
                </span>
              </SelectValue>
            </SelectTrigger>
            <SelectContent className='z-[10002]'>
              <SelectItem value='_all'>
                <span className='text-muted-foreground'>
                  {t('filterAllCampaigns')}
                </span>
              </SelectItem>
              {campaigns.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  <span className='block max-w-[460px] truncate'>{c.name}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className='relative min-w-[200px] max-w-full flex-[0_0_220px]'>
          <FileText className='pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
          <Select
            value={collection || '_all'}
            onValueChange={(v) => onCollectionChange(v === '_all' ? '' : v)}
          >
            <SelectTrigger
              className='h-10 w-full min-w-0 overflow-hidden pl-9 text-sm'
              aria-label={t('filterCollectionAria')}
            >
              <SelectValue placeholder={t('filterCollection')}>
                <span className='block w-full truncate'>
                  {collection ? collection : t('filterCollection')}
                </span>
              </SelectValue>
            </SelectTrigger>
            <SelectContent className='z-[10002]'>
              <SelectItem value='_all'>
                <span className='text-muted-foreground'>
                  {t('filterAllCollections')}
                </span>
              </SelectItem>
              {collectionOptions.map((c) => (
                <SelectItem key={c} value={c}>
                  <span className='block max-w-[460px] truncate'>{c}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className='relative min-w-[170px] max-w-full flex-[0_0_180px]'>
          <Smartphone className='pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
          <Select
            value={platform || '_all'}
            onValueChange={(v) => onPlatformChange(v === '_all' ? '' : v)}
          >
            <SelectTrigger
              className='h-10 w-full min-w-0 overflow-hidden pl-9 text-sm'
              aria-label={t('filterPlatformAria')}
            >
              <SelectValue placeholder={t('filterPlatform')}>
                <span className='block w-full truncate'>
                  {platform ? platform : t('filterPlatform')}
                </span>
              </SelectValue>
            </SelectTrigger>
            <SelectContent className='z-[10002]'>
              <SelectItem value='_all'>
                <span className='text-muted-foreground'>
                  {t('filterAllPlatforms')}
                </span>
              </SelectItem>
              {platformOptions.map((p) => (
                <SelectItem key={p} value={p}>
                  <span className='capitalize'>{p}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          size='sm'
          className='h-10 gap-1.5 text-sm font-medium'
          onClick={onApply}
        >
          <Filter className='size-4' />
          <span className='sm:hidden'>{t('applyFilter')}</span>
        </Button>
      </div>
    </div>
  );
}

function EmptyState({
  hasFilters,
  onClear,
  executionId
}: {
  hasFilters?: boolean;
  onClear?: () => void;
  executionId?: string;
}) {
  const t = useTranslations('coreEmptyState');
  const { canCreate: canCreateCampaigns } = useResourcePermissions('campaigns');

  return (
    <CoreEmptyState
      icon={Database}
      variant={hasFilters ? 'no-results' : 'no-data'}
      title={hasFilters ? t('content.titleFiltered') : t('content.titleNoData')}
      description={
        hasFilters
          ? t('content.descriptionFiltered')
          : t('content.descriptionNoData')
      }
      readOnlyHint={canCreateCampaigns ? undefined : t('readOnlyHint')}
      trackingKey={
        hasFilters
          ? 'content-empty-filtered'
          : canCreateCampaigns
            ? 'content-empty'
            : 'content-empty-readonly'
      }
      cta={
        hasFilters
          ? { label: t('content.ctaClearFilters'), onClick: onClear }
          : { label: t('content.ctaCampaigns'), href: ROUTES.CAMPAIGNS.ROOT }
      }
      secondaryCta={
        executionId
          ? {
              label: t('content.ctaExecution'),
              href: ROUTES.CONTENT.BY_EXECUTION(executionId)
            }
          : undefined
      }
    />
  );
}

function TableSkeleton() {
  return (
    <div className='overflow-hidden rounded-xl border border-border/60 bg-card'>
      <div className='border-b border-border/60 bg-muted/30 px-4 py-3'>
        <div className='h-3 w-32 animate-pulse rounded bg-muted' />
      </div>
      <div className='divide-y divide-border/40'>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className='flex items-center gap-4 px-4 py-4'>
            <div className='size-8 animate-pulse rounded-full bg-muted' />
            <div className='flex-1 space-y-2'>
              <div className='h-3 w-1/3 animate-pulse rounded bg-muted' />
              <div className='h-3 w-2/3 animate-pulse rounded bg-muted/70' />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Pagination ────────────────────────────────────────────────────────────────

function Pagination({
  page,
  totalPages,
  total,
  pageSize,
  onPageChange,
  onPageSizeChange
}: {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  onPageChange: (p: number) => void;
  onPageSizeChange: (n: number) => void;
}) {
  const t = useTranslations('contentFeature.list');
  const locale = useLocale();
  const from = page * pageSize + 1;
  const to = Math.min((page + 1) * pageSize, total);
  return (
    <div className='flex flex-wrap items-center justify-between gap-3'>
      <p className='text-xs text-muted-foreground'>
        {t('paginationShowing', {
          from: from.toLocaleString(locale),
          to: to.toLocaleString(locale),
          total: total.toLocaleString(locale)
        })}
      </p>
      <div className='flex items-center gap-1.5'>
        <Select
          value={String(pageSize)}
          onValueChange={(v) => onPageSizeChange(Number(v))}
        >
          <SelectTrigger className='h-8 w-[88px] text-xs'>
            <SelectValue placeholder='50' />
          </SelectTrigger>
          <SelectContent align='end'>
            {[10, 25, 50, 100].map((n) => (
              <SelectItem key={n} value={String(n)}>
                {t('paginationPerPage', { size: n })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          size='sm'
          variant='outline'
          className='h-8 gap-1 px-2 text-xs'
          onClick={() => onPageChange(page - 1)}
          disabled={page === 0}
        >
          <ChevronLeft size={14} />
          {t('paginationPrev')}
        </Button>
        <span className='rounded-md border border-border/60 bg-muted/50 px-3 py-1 text-xs font-medium tabular-nums'>
          {page + 1} / {totalPages}
        </span>
        <Button
          size='sm'
          variant='outline'
          className='h-8 gap-1 px-2 text-xs'
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages - 1}
        >
          {t('paginationNext')}
          <ChevronRight size={14} />
        </Button>
      </div>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

interface Props {
  /** Pre-filter by campaign ID (e.g. opened from campaign detail). */
  defaultCampaignId?: string;
  /** Pre-filter by execution / run ID. */
  defaultExecutionId?: string;
  /** Pre-filter by a content hash, e.g. parent post opened from a comment. */
  defaultContentHash?: string;
  /** Select the initial content dataset when rendered inside a parent tab bar. */
  defaultContentType?: 'fb_post' | 'fb_comment';
  /** Keep the legacy local post/comment switch for existing callers. */
  showContentTypeTabs?: boolean;
}

export function ContentViewer({
  defaultCampaignId,
  defaultExecutionId,
  defaultContentHash,
  defaultContentType = DEFAULT_CONTENT_TYPE,
  showContentTypeTabs = true
}: Props) {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const [campaignId, setCampaignId] = useState(defaultCampaignId ?? '');
  const [executionId, setExecutionId] = useState(defaultExecutionId ?? '');
  const [collection, setCollection] = useState('');
  const [platform, setPlatform] = useState('');
  const [contentType, setContentType] = useState(defaultContentType);
  const [exportOpen, setExportOpen] = useState(false);
  const [pageSize, setPageSize] = useState(50);
  const tList = useTranslations('contentFeature.list');
  const tExport = useTranslations('contentFeature.export');
  const { canDelete } = useResourcePermissions('content');

  const openContentDetail = (item: ContentItem) => {
    router.push(ROUTES.CONTENT.DETAIL(item.id));
  };

  const {
    items,
    total,
    page,
    totalPages,
    loading,
    error,
    filters,
    applyFilters,
    setPage,
    deleteItem,
    reload
  } = useContent(
    {
      campaign_id: defaultCampaignId || undefined,
      run_id: defaultExecutionId || undefined,
      content_hash: defaultContentHash || undefined,
      content_type: defaultContentHash ? undefined : defaultContentType
    },
    { pageSize }
  );

  const handleExport = (_format: ExportFormat) => {
    setExportOpen(true);
  };

  const handleApply = (overrides?: { contentType?: string }) => {
    const ct =
      overrides?.contentType !== undefined
        ? overrides.contentType
        : contentType;
    applyFilters({
      search: search || undefined,
      campaign_id: campaignId || undefined,
      run_id: executionId || undefined,
      collection: collection || undefined,
      platform: platform || undefined,
      content_type: ct || undefined
    });
  };

  const applyWithNext = (next: {
    search?: string;
    campaignId?: string;
    executionId?: string;
    collection?: string;
    platform?: string;
    contentType?: string;
  }) => {
    const nextSearch = next.search ?? search;
    const nextCampaignId = next.campaignId ?? campaignId;
    const nextExecutionId = next.executionId ?? executionId;
    const nextCollection = next.collection ?? collection;
    const nextPlatform = next.platform ?? platform;
    const nextContentType = next.contentType ?? contentType;
    applyFilters({
      search: nextSearch || undefined,
      campaign_id: nextCampaignId || undefined,
      run_id: nextExecutionId || undefined,
      collection: nextCollection || undefined,
      platform: nextPlatform || undefined,
      content_type: nextContentType || undefined
    });
  };

  const handleCampaignIdChange = (v: string) => {
    setCampaignId(v);
    applyWithNext({ campaignId: v });
  };

  const handleCollectionChange = (v: string) => {
    setCollection(v);
    applyWithNext({ collection: v });
  };

  const handlePlatformChange = (v: string) => {
    setPlatform(v);
    applyWithNext({ platform: v });
  };

  const handleViewParent = async (parentId: string) => {
    try {
      const res = await contentApi.list({
        content_hash: parentId,
        limit: 1,
        offset: 0
      });
      const parent = res.items[0];
      if (parent) {
        router.push(ROUTES.CONTENT.DETAIL(parent.id));
        return;
      }
    } catch {
      // Fallback to the filtered list below.
    }
    applyFilters({
      content_hash: parentId,
      content_type: DEFAULT_CONTENT_TYPE
    });
    setSearch('');
    setCampaignId('');
    setCollection('');
    setPlatform('');
    setContentType(DEFAULT_CONTENT_TYPE);
  };

  const handleContentTypeChange = (v: ContentDatasetType) => {
    setContentType(v);
    handleApply({ contentType: v });
  };

  const handleClear = () => {
    setSearch('');
    setCampaignId('');
    setExecutionId('');
    setCollection('');
    setPlatform('');
    setContentType(defaultContentType);
    applyFilters({ content_type: defaultContentType });
  };

  const hasFilters = !!(
    search ||
    campaignId ||
    executionId ||
    collection ||
    platform ||
    (showContentTypeTabs &&
      contentType &&
      contentType !== DEFAULT_CONTENT_TYPE) ||
    filters.content_hash
  );

  return (
    <div className='space-y-5'>
      <StatsBar />

      <div className='overflow-hidden rounded-2xl border border-border/60 bg-card shadow-sm'>
        {/* Header */}
        <div className='flex flex-wrap items-center justify-between gap-3 border-b border-border/60 bg-gradient-to-b from-muted/40 to-transparent px-5 py-4'>
          <div>
            <p className='text-base font-semibold leading-tight text-foreground'>
              {tList('panelTitle')}
            </p>
            <p className='mt-1 text-xs text-muted-foreground'>
              {tList('panelSubtitle')}
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Badge
              variant='secondary'
              className='h-8 gap-1.5 rounded-full px-3 text-xs font-semibold tabular-nums'
            >
              <Database className='size-3.5' />
              {tList('recordCount', { count: total })}
            </Badge>
            <Button asChild size='sm' variant='ghost' className='h-9 text-xs'>
              <Link href={ROUTES.CONTENT.EXPORTS}>
                {tExport('historyLink')}
              </Link>
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  size='sm'
                  variant='outline'
                  className='h-9 gap-1.5 text-xs'
                  disabled={total === 0}
                >
                  <Download className='size-3.5' />
                  {tExport('exportButton')}
                  <ChevronDown className='size-3' />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align='end'>
                <DropdownMenuItem
                  onClick={() => handleExport('csv')}
                  className='cursor-pointer'
                >
                  <FileText className='mr-2 size-3.5' />
                  {tExport('formatCsv')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => handleExport('xlsx')}
                  className='cursor-pointer'
                >
                  <Database className='mr-2 size-3.5' />
                  {tExport('formatXlsx')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {filters.content_hash ? (
          <div className='border-b border-blue-500/20 bg-blue-500/[0.04] px-5 py-2.5'>
            <div className='flex flex-wrap items-center justify-between gap-2 text-xs'>
              <div className='flex min-w-0 items-center gap-2 text-blue-800 dark:text-blue-200'>
                <FileText className='size-3.5 shrink-0' />
                <span className='font-medium'>
                  {tList('parentHashFilterTitle')}
                </span>
                <span className='min-w-0 truncate rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted-foreground'>
                  {filters.content_hash}
                </span>
              </div>
              <Button
                type='button'
                size='sm'
                variant='ghost'
                className='h-7 gap-1 px-2 text-xs'
                onClick={handleClear}
              >
                <X className='size-3' />
                {tList('clearParentFilter')}
              </Button>
            </div>
          </div>
        ) : null}

        {/* Filters */}
        <div className='border-b border-border/60 bg-muted/10 px-5 py-4'>
          <Filters
            search={search}
            onSearchChange={setSearch}
            campaignId={campaignId}
            onCampaignIdChange={handleCampaignIdChange}
            collection={collection}
            onCollectionChange={handleCollectionChange}
            platform={platform}
            onPlatformChange={handlePlatformChange}
            contentType={contentType}
            onContentTypeChange={handleContentTypeChange}
            onRefresh={() => {
              handleApply();
              reload();
            }}
            onApply={() => handleApply()}
            onClear={handleClear}
            loading={loading}
            showContentTypeTabs={showContentTypeTabs}
          />
        </div>

        {/* Content */}
        <div className='p-5'>
          {error ? (
            <div
              role='alert'
              className='flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-xs text-destructive'
            >
              <X className='mt-0.5 size-4 shrink-0' />
              <span>{error}</span>
            </div>
          ) : loading ? (
            <TableSkeleton />
          ) : items.length === 0 ? (
            <EmptyState
              hasFilters={hasFilters}
              onClear={handleClear}
              executionId={executionId || undefined}
            />
          ) : (
            <ContentTable
              items={items}
              onViewItem={openContentDetail}
              onDeleteItem={deleteItem}
              onViewParent={handleViewParent}
              canDelete={canDelete}
            />
          )}
        </div>

        {/* Pagination */}
        {!loading && total > 0 && (
          <div className='border-t border-border/60 bg-muted/10 px-5 py-3'>
            <Pagination
              page={page}
              totalPages={totalPages}
              total={total}
              pageSize={pageSize}
              onPageChange={setPage}
              onPageSizeChange={(n) => {
                setPage(0);
                setPageSize(n);
              }}
            />
          </div>
        )}
      </div>

      <ContentExportDialog
        open={exportOpen}
        onOpenChange={setExportOpen}
        filters={filters}
        itemCount={total}
      />
    </div>
  );
}
