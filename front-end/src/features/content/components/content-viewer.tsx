'use client';

import { useState } from 'react';
import {
  Search,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Trash2,
  ExternalLink,
  Eye,
  Database,
  TrendingUp,
  Smartphone,
  FileText,
  MessageCircle,
  Newspaper,
  Heart,
  Share2,
  ThumbsUp,
  Clock,
  CornerDownRight,
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
import { useContent, useContentStats } from '../hooks/use-content';
import {
  contentApi,
  type ContentItem,
  type ExportFormat
} from '../services/api';
import { ContentDetailDialog } from './content-detail-dialog';
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
  const { stats, loading } = useContentStats();
  if (loading && !stats) return <StatsBarSkeleton />;
  if (!stats) return null;
  return (
    <div className='grid grid-cols-2 gap-3 sm:grid-cols-4'>
      <StatCard
        icon={<Database className='size-5' />}
        label='Tổng bản ghi'
        value={stats.total_items.toLocaleString()}
        tint='primary'
      />
      <StatCard
        icon={<TrendingUp className='size-5' />}
        label='Nền tảng'
        value={Object.keys(stats.by_platform).length.toString()}
        tint='emerald'
      />
      <StatCard
        icon={<FileText className='size-5' />}
        label='Bộ sưu tập'
        value={Object.keys(stats.by_collection).length.toString()}
        tint='blue'
      />
      <StatCard
        icon={<Smartphone className='size-5' />}
        label='Cào gần nhất'
        value={
          stats.latest_extraction
            ? new Date(stats.latest_extraction).toLocaleString('vi-VN', {
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

const CONTENT_TYPE_TABS = [
  { value: '', label: 'Tất cả', icon: <Database className='size-3.5' /> },
  {
    value: 'group_post',
    label: 'Bài đăng',
    icon: <Newspaper className='size-3.5' />
  },
  {
    value: 'comment',
    label: 'Bình luận',
    icon: <MessageCircle className='size-3.5' />
  }
] as const;

interface FiltersProps {
  search: string;
  onSearchChange: (v: string) => void;
  campaignId: string;
  onCampaignIdChange: (v: string) => void;
  collection: string;
  onCollectionChange: (v: string) => void;
  platform: string;
  onPlatformChange: (v: string) => void;
  contentType: string;
  onContentTypeChange: (v: string) => void;
  onRefresh: () => void;
  onApply: () => void;
  onClear: () => void;
  loading: boolean;
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
  loading
}: FiltersProps) {
  const { data: campaigns = [], isLoading: loadingCampaigns } = useCampaigns();
  const { stats } = useContentStats();

  const onKeyEnter = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') onApply();
  };
  const hasFilters = !!(
    search ||
    campaignId ||
    collection ||
    platform ||
    contentType
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
        <div className='inline-flex items-center gap-1 rounded-xl bg-muted/60 p-1 ring-1 ring-border/40'>
          {CONTENT_TYPE_TABS.map((tab) => {
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

        <div className='flex items-center gap-2'>
          {hasFilters && (
            <Button
              size='sm'
              variant='ghost'
              className='h-9 gap-1.5 text-xs text-muted-foreground hover:text-foreground'
              onClick={onClear}
            >
              <X className='size-3.5' />
              Xoá lọc
            </Button>
          )}
          <Button
            size='sm'
            variant='outline'
            className='h-9 gap-1.5 text-xs'
            onClick={onRefresh}
            disabled={loading}
            title='Tải lại'
          >
            <RefreshCw className={cn('size-3.5', loading && 'animate-spin')} />
            Tải lại
          </Button>
        </div>
      </div>

      {/* Inputs row */}
      <div className='flex flex-wrap items-center gap-2'>
        <div className='relative min-w-[260px] flex-1'>
          <Search className='pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
          <Input
            className='h-10 pl-9 text-sm'
            placeholder='Tìm kiếm theo nội dung, tác giả…'
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            onKeyDown={onKeyEnter}
            aria-label='Tìm kiếm'
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
              aria-label='Lọc theo chiến dịch'
            >
              <SelectValue placeholder='Chiến dịch'>
                <span className='block w-full truncate'>
                  {campaignId
                    ? (selectedCampaign?.name ?? campaignId)
                    : 'Chiến dịch'}
                </span>
              </SelectValue>
            </SelectTrigger>
            <SelectContent className='z-[10002]'>
              <SelectItem value='_all'>
                <span className='text-muted-foreground'>Tất cả chiến dịch</span>
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
              aria-label='Lọc theo bộ sưu tập'
            >
              <SelectValue placeholder='Bộ sưu tập'>
                <span className='block w-full truncate'>
                  {collection ? collection : 'Bộ sưu tập'}
                </span>
              </SelectValue>
            </SelectTrigger>
            <SelectContent className='z-[10002]'>
              <SelectItem value='_all'>
                <span className='text-muted-foreground'>Tất cả bộ sưu tập</span>
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
              aria-label='Lọc theo nền tảng'
            >
              <SelectValue placeholder='Nền tảng'>
                <span className='block w-full truncate'>
                  {platform ? platform : 'Nền tảng'}
                </span>
              </SelectValue>
            </SelectTrigger>
            <SelectContent className='z-[10002]'>
              <SelectItem value='_all'>
                <span className='text-muted-foreground'>Tất cả nền tảng</span>
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
          <span className='sm:hidden'>Lọc</span>
        </Button>
      </div>
    </div>
  );
}

// ── Table (Tất cả / Post) ─────────────────────────────────────────────────────

const PLATFORM_STYLES: Record<string, string> = {
  facebook: 'bg-blue-500/10 text-blue-700 ring-blue-500/20 dark:text-blue-300',
  instagram: 'bg-pink-500/10 text-pink-700 ring-pink-500/20 dark:text-pink-300',
  tiktok:
    'bg-neutral-900/10 text-neutral-900 ring-neutral-900/20 dark:bg-neutral-50/10 dark:text-neutral-100',
  twitter: 'bg-sky-500/10 text-sky-700 ring-sky-500/20 dark:text-sky-300',
  x: 'bg-sky-500/10 text-sky-700 ring-sky-500/20 dark:text-sky-300',
  youtube: 'bg-red-500/10 text-red-700 ring-red-500/20 dark:text-red-300'
};

function PlatformBadge({ name }: { name: string }) {
  const key = (name || '').toLowerCase();
  const cls =
    PLATFORM_STYLES[key] ?? 'bg-muted text-muted-foreground ring-border';
  return (
    <span
      className={cn(
        'inline-flex h-5 items-center rounded-md px-1.5 text-[11px] font-semibold capitalize ring-1 ring-inset',
        cls
      )}
    >
      {name}
    </span>
  );
}

function EmptyState({
  hasFilters,
  onClear
}: {
  hasFilters?: boolean;
  onClear?: () => void;
}) {
  return (
    <div className='flex flex-col items-center justify-center rounded-xl border border-dashed border-border/60 py-20 text-center'>
      <div className='mb-3 flex size-14 items-center justify-center rounded-full bg-muted/60'>
        <Database
          className='size-7 text-muted-foreground/60'
          strokeWidth={1.5}
        />
      </div>
      <p className='text-sm font-semibold text-foreground'>
        {hasFilters ? 'Không có kết quả phù hợp' : 'Chưa có dữ liệu'}
      </p>
      <p className='mt-1 max-w-xs text-xs text-muted-foreground/80'>
        {hasFilters
          ? 'Thử thay đổi từ khoá hoặc xoá bộ lọc để xem tất cả.'
          : 'Chạy kịch bản có bước extract để thu thập dữ liệu từ các nền tảng.'}
      </p>
      {hasFilters && onClear && (
        <Button
          size='sm'
          variant='outline'
          className='mt-4 gap-1.5'
          onClick={onClear}
        >
          <X className='size-3.5' />
          Xoá bộ lọc
        </Button>
      )}
    </div>
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

function ContentTable({
  items,
  onViewItem,
  onDeleteItem,
  onViewParent,
  hasFilters,
  onClear
}: {
  items: ContentItem[];
  onViewItem: (item: ContentItem) => void;
  onDeleteItem: (id: string) => void;
  onViewParent: (parentId: string) => void;
  hasFilters: boolean;
  onClear: () => void;
}) {
  if (items.length === 0)
    return <EmptyState hasFilters={hasFilters} onClear={onClear} />;
  return (
    <div className='overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm'>
      <div className='overflow-x-auto'>
        <table className='w-full text-sm'>
          <thead className='sticky top-0 z-10 bg-muted/50 backdrop-blur-sm'>
            <tr className='border-b border-border/60 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground'>
              <th className='px-4 py-3 text-left'>Thời gian</th>
              <th className='px-4 py-3 text-left'>Nền tảng</th>
              <th className='px-4 py-3 text-left'>Nội dung</th>
              <th className='px-4 py-3 text-left'>Tác giả</th>
              <th className='px-4 py-3 text-right'>Tương tác</th>
              <th className='px-4 py-3 text-left'>Bộ sưu tập</th>
              <th className='w-24 px-4 py-3 text-right'>Hành động</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, idx) => (
              <tr
                key={item.id}
                className={cn(
                  'group cursor-pointer border-b border-border/40 transition-colors last:border-b-0',
                  idx % 2 === 1 && 'bg-muted/10',
                  'hover:bg-primary/[0.05]'
                )}
                onClick={() => onViewItem(item)}
              >
                <td className='whitespace-nowrap px-4 py-3.5 align-top font-mono text-[11px] text-muted-foreground'>
                  {item.extracted_at
                    ? new Date(item.extracted_at).toLocaleString('vi-VN', {
                        dateStyle: 'short',
                        timeStyle: 'short'
                      })
                    : '–'}
                </td>
                <td className='px-4 py-3.5 align-top'>
                  <div className='flex flex-col items-start gap-1'>
                    {item.platform && <PlatformBadge name={item.platform} />}
                    <span className='text-[11px] font-medium text-muted-foreground'>
                      {item.content_type}
                    </span>
                    {item.parent_id && (
                      <button
                        type='button'
                        onClick={(e) => {
                          e.stopPropagation();
                          onViewParent(item.parent_id!);
                        }}
                        className='inline-flex cursor-pointer items-center gap-1 rounded px-1 py-0.5 text-[10px] font-medium text-blue-600 transition-colors hover:bg-blue-500/10 hover:underline dark:text-blue-400'
                      >
                        <FileText size={10} /> Bài gốc
                      </button>
                    )}
                  </div>
                </td>
                <td className='max-w-[380px] px-4 py-3.5 align-top'>
                  <p className='line-clamp-2 leading-snug text-foreground/90'>
                    {item.title || item.body || (
                      <span className='italic text-muted-foreground'>
                        (trống)
                      </span>
                    )}
                  </p>
                  {item.url && (
                    <a
                      href={item.url}
                      target='_blank'
                      rel='noopener noreferrer'
                      className='mt-1.5 inline-flex max-w-full items-center gap-1 text-[11px] text-primary/80 hover:text-primary hover:underline'
                      onClick={(e) => e.stopPropagation()}
                    >
                      <ExternalLink size={11} className='shrink-0' />
                      <span className='max-w-[260px] truncate'>{item.url}</span>
                    </a>
                  )}
                </td>
                <td className='px-4 py-3.5 align-top text-foreground/90'>
                  {item.author || (
                    <span className='text-muted-foreground'>–</span>
                  )}
                </td>
                <td className='whitespace-nowrap px-4 py-3.5 text-right align-top font-mono text-xs text-muted-foreground'>
                  {[item.likes_count, item.comments_count, item.shares_count]
                    .filter((v) => v != null)
                    .join(' / ') || '–'}
                </td>
                <td className='px-4 py-3.5 align-top'>
                  <span className='inline-flex items-center rounded-md border border-border/60 bg-background px-2 py-0.5 text-[11px] font-medium text-foreground/80'>
                    {item.collection}
                  </span>
                </td>
                <td className='px-4 py-3.5 align-top'>
                  <div className='flex items-center justify-end gap-1 opacity-60 transition-opacity focus-within:opacity-100 group-hover:opacity-100'>
                    <Button
                      size='sm'
                      variant='ghost'
                      className='h-8 w-8 p-0'
                      onClick={(e) => {
                        e.stopPropagation();
                        onViewItem(item);
                      }}
                      title='Xem chi tiết'
                      aria-label='Xem chi tiết'
                    >
                      <Eye size={15} />
                    </Button>
                    <Button
                      size='sm'
                      variant='ghost'
                      className='h-8 w-8 p-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive'
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteItem(item.id);
                      }}
                      title='Xoá'
                      aria-label='Xoá'
                    >
                      <Trash2 size={15} />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Card feed (Comment) ───────────────────────────────────────────────────────

function ContentFeed({
  items,
  onViewItem,
  onDeleteItem,
  onViewParent,
  hasFilters,
  onClear
}: {
  items: ContentItem[];
  onViewItem: (item: ContentItem) => void;
  onDeleteItem: (id: string) => void;
  onViewParent: (parentId: string) => void;
  hasFilters: boolean;
  onClear: () => void;
}) {
  if (items.length === 0)
    return <EmptyState hasFilters={hasFilters} onClear={onClear} />;

  return (
    <div className='space-y-3'>
      {items.map((item) => (
        <ContentCard
          key={item.id}
          item={item}
          onView={() => onViewItem(item)}
          onDelete={() => onDeleteItem(item.id)}
          onViewParent={
            item.parent_id ? () => onViewParent(item.parent_id!) : undefined
          }
        />
      ))}
    </div>
  );
}

function ContentCard({
  item,
  onView,
  onDelete,
  onViewParent
}: {
  item: ContentItem;
  onView: () => void;
  onDelete: () => void;
  onViewParent?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isComment = item.item_level > 0;
  const body = item.body ?? item.title ?? '';
  const isLong = body.length > 240;
  const displayBody = isLong && !expanded ? body.slice(0, 240) + '…' : body;

  const time = item.extracted_at
    ? new Date(item.extracted_at).toLocaleString('vi-VN', {
        dateStyle: 'short',
        timeStyle: 'short'
      })
    : '';

  const initials = item.author
    ? item.author
        .split(' ')
        .map((w) => w[0])
        .slice(0, 2)
        .join('')
        .toUpperCase()
    : '?';

  return (
    <div
      className={cn(
        'group relative rounded-xl border bg-card transition-all hover:border-primary/30 hover:shadow-md',
        isComment
          ? 'ml-6 border-l-2 border-border/40 border-l-blue-400/60 bg-blue-500/[0.02]'
          : 'border-border/50'
      )}
    >
      {isComment && (
        <div className='absolute -left-6 top-4 flex items-center text-blue-400/60'>
          <CornerDownRight size={14} />
        </div>
      )}

      <div className='p-4'>
        <div className='mb-3 flex items-start justify-between gap-3'>
          <div className='flex items-center gap-3'>
            <div
              className={cn(
                'flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-bold',
                isComment
                  ? 'bg-blue-500/15 text-blue-600 dark:text-blue-400'
                  : 'bg-primary/15 text-primary'
              )}
            >
              {initials}
            </div>
            <div className='min-w-0'>
              <div className='flex flex-wrap items-center gap-1.5'>
                <span className='text-sm font-semibold text-foreground'>
                  {item.author || 'Ẩn danh'}
                </span>
                {item.platform && (
                  <Badge
                    variant='secondary'
                    className='h-5 px-1.5 text-[10px] capitalize'
                  >
                    {item.platform}
                  </Badge>
                )}
                {isComment && (
                  <Badge className='h-5 bg-blue-500/15 px-1.5 text-[10px] text-blue-600 hover:bg-blue-500/15 dark:text-blue-400'>
                    bình luận
                  </Badge>
                )}
              </div>
              <div className='mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground'>
                <Clock size={10} />
                <span>{time}</span>
                {item.collection && (
                  <>
                    <span>·</span>
                    <span className='rounded bg-muted px-1.5 py-0.5'>
                      {item.collection}
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>

          <div className='flex shrink-0 items-center gap-0.5 opacity-60 transition-opacity focus-within:opacity-100 group-hover:opacity-100'>
            {onViewParent && (
              <Button
                size='sm'
                variant='ghost'
                className='h-7 gap-1 px-2 text-[11px] text-blue-600'
                onClick={onViewParent}
              >
                <FileText size={11} /> Bài gốc
              </Button>
            )}
            <Button
              size='sm'
              variant='ghost'
              className='h-7 w-7 p-0'
              onClick={onView}
              aria-label='Xem chi tiết'
            >
              <Eye size={13} />
            </Button>
            <Button
              size='sm'
              variant='ghost'
              className='h-7 w-7 p-0 hover:text-destructive'
              onClick={onDelete}
              aria-label='Xoá'
            >
              <Trash2 size={13} />
            </Button>
          </div>
        </div>

        {body && (
          <div className='mb-3'>
            <p className='whitespace-pre-wrap text-sm leading-relaxed text-foreground/90'>
              {displayBody}
            </p>
            {isLong && (
              <button
                type='button'
                onClick={() => setExpanded((v) => !v)}
                className='mt-1 cursor-pointer text-xs font-medium text-primary hover:underline'
              >
                {expanded ? 'Thu gọn' : 'Xem thêm'}
              </button>
            )}
          </div>
        )}

        {item.url && (
          <a
            href={item.url}
            target='_blank'
            rel='noopener noreferrer'
            className='mb-3 flex items-center gap-1 truncate text-xs text-primary/80 hover:text-primary hover:underline'
          >
            <ExternalLink size={11} className='shrink-0' />
            <span className='truncate'>{item.url}</span>
          </a>
        )}

        {(item.likes_count != null ||
          item.comments_count != null ||
          item.shares_count != null ||
          item.views_count != null) && (
          <div className='flex items-center gap-4 border-t border-border/30 pt-3 text-xs text-muted-foreground'>
            {item.likes_count != null && (
              <span className='flex items-center gap-1.5'>
                <ThumbsUp size={12} className='text-blue-500' />
                {item.likes_count.toLocaleString()}
              </span>
            )}
            {item.comments_count != null && (
              <span className='flex items-center gap-1.5'>
                <MessageCircle size={12} className='text-emerald-500' />
                {item.comments_count.toLocaleString()}
              </span>
            )}
            {item.shares_count != null && (
              <span className='flex items-center gap-1.5'>
                <Share2 size={12} className='text-violet-500' />
                {item.shares_count.toLocaleString()}
              </span>
            )}
            {item.likes_count == null &&
              item.shares_count == null &&
              item.views_count != null && (
                <span className='flex items-center gap-1.5'>
                  <Heart size={12} className='text-rose-500' />
                  {item.views_count.toLocaleString()}
                </span>
              )}
          </div>
        )}
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
  const from = page * pageSize + 1;
  const to = Math.min((page + 1) * pageSize, total);
  return (
    <div className='flex flex-wrap items-center justify-between gap-3'>
      <p className='text-xs text-muted-foreground'>
        Hiển thị{' '}
        <span className='font-semibold text-foreground'>
          {from.toLocaleString()}–{to.toLocaleString()}
        </span>{' '}
        trong tổng{' '}
        <span className='font-semibold text-foreground'>
          {total.toLocaleString()}
        </span>{' '}
        bản ghi
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
                {n}/trang
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
          Trước
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
          Sau
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
}

export function ContentViewer({ defaultCampaignId }: Props) {
  const [search, setSearch] = useState('');
  const [campaignId, setCampaignId] = useState(defaultCampaignId ?? '');
  const [collection, setCollection] = useState('');
  const [platform, setPlatform] = useState('');
  const [contentType, setContentType] = useState('');
  const [viewingItem, setViewingItem] = useState<ContentItem | null>(null);
  const [exporting, setExporting] = useState(false);
  const [pageSize, setPageSize] = useState(50);

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
      campaign_id: defaultCampaignId || undefined
    },
    { pageSize }
  );

  const handleExport = (format: ExportFormat) => {
    setExporting(true);
    try {
      contentApi.exportStream(filters, format);
    } finally {
      setTimeout(() => setExporting(false), 1200);
    }
  };

  const handleApply = (overrides?: { contentType?: string }) => {
    const ct =
      overrides?.contentType !== undefined
        ? overrides.contentType
        : contentType;
    applyFilters({
      search: search || undefined,
      campaign_id: campaignId || undefined,
      collection: collection || undefined,
      platform: platform || undefined,
      content_type: ct || undefined
    });
  };

  const applyWithNext = (next: {
    search?: string;
    campaignId?: string;
    collection?: string;
    platform?: string;
    contentType?: string;
  }) => {
    const nextSearch = next.search ?? search;
    const nextCampaignId = next.campaignId ?? campaignId;
    const nextCollection = next.collection ?? collection;
    const nextPlatform = next.platform ?? platform;
    const nextContentType = next.contentType ?? contentType;
    applyFilters({
      search: nextSearch || undefined,
      campaign_id: nextCampaignId || undefined,
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

  const handleViewParent = (parentId: string) => {
    applyFilters({ content_hash: parentId });
    setSearch('');
    setCampaignId('');
    setCollection('');
    setPlatform('');
    setContentType('');
  };

  const handleContentTypeChange = (v: string) => {
    setContentType(v);
    handleApply({ contentType: v });
  };

  const handleClear = () => {
    setSearch('');
    setCampaignId('');
    setCollection('');
    setPlatform('');
    setContentType('');
    applyFilters({});
  };

  const hasFilters = !!(
    search ||
    campaignId ||
    collection ||
    platform ||
    contentType
  );

  return (
    <div className='space-y-5'>
      <StatsBar />

      <div className='overflow-hidden rounded-2xl border border-border/60 bg-card shadow-sm'>
        {/* Header */}
        <div className='flex flex-wrap items-center justify-between gap-3 border-b border-border/60 bg-gradient-to-b from-muted/40 to-transparent px-5 py-4'>
          <div>
            <p className='text-base font-semibold leading-tight text-foreground'>
              Dữ liệu đã thu thập
            </p>
            <p className='mt-1 text-xs text-muted-foreground'>
              Tất cả nội dung được cào từ các lần chạy kịch bản
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Badge
              variant='secondary'
              className='h-8 gap-1.5 rounded-full px-3 text-xs font-semibold tabular-nums'
            >
              <Database className='size-3.5' />
              {total.toLocaleString()} bản ghi
            </Badge>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  size='sm'
                  variant='outline'
                  className='h-9 gap-1.5 text-xs'
                  disabled={exporting || total === 0}
                >
                  {exporting ? (
                    <RefreshCw className='size-3.5 animate-spin' />
                  ) : (
                    <Download className='size-3.5' />
                  )}
                  Export
                  <ChevronDown className='size-3' />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align='end'>
                <DropdownMenuItem
                  onClick={() => handleExport('csv')}
                  className='cursor-pointer'
                >
                  <FileText className='mr-2 size-3.5' />
                  CSV (streaming)
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => handleExport('xlsx')}
                  className='cursor-pointer'
                >
                  <Database className='mr-2 size-3.5' />
                  Excel (.xlsx)
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

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
          ) : contentType === 'comment' ? (
            <ContentFeed
              items={items}
              onViewItem={setViewingItem}
              onDeleteItem={deleteItem}
              onViewParent={handleViewParent}
              hasFilters={hasFilters}
              onClear={handleClear}
            />
          ) : (
            <ContentTable
              items={items}
              onViewItem={setViewingItem}
              onDeleteItem={deleteItem}
              onViewParent={handleViewParent}
              hasFilters={hasFilters}
              onClear={handleClear}
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

      <ContentDetailDialog
        item={viewingItem}
        onClose={() => setViewingItem(null)}
        onViewParent={handleViewParent}
      />
    </div>
  );
}
