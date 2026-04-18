'use client';

import { useState } from 'react';
import {
  Search, RefreshCw, ChevronLeft, ChevronRight,
  Trash2, ExternalLink, Eye, Database, TrendingUp,
  Smartphone, FileText, MessageCircle, Newspaper,
  Heart, Share2, ThumbsUp, Clock, CornerDownRight,
  Download, ChevronDown,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import { useContent, useContentStats } from '../hooks/use-content';
import { contentApi, type ContentItem, type ExportFormat } from '../services/api';
import { ContentDetailDialog } from './content-detail-dialog';

// ── Stats bar ────────────────────────────────────────────────────────────────

function StatsBar() {
  const { stats } = useContentStats();
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
        label='Platforms'
        value={Object.keys(stats.by_platform).length.toString()}
        tint='emerald'
      />
      <StatCard
        icon={<FileText className='size-5' />}
        label='Collections'
        value={Object.keys(stats.by_collection).length.toString()}
        tint='blue'
      />
      <StatCard
        icon={<Smartphone className='size-5' />}
        label='Lần cào gần nhất'
        value={stats.latest_extraction ? new Date(stats.latest_extraction).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' }) : '–'}
        tint='violet'
      />
    </div>
  );
}

type StatTint = 'primary' | 'emerald' | 'blue' | 'violet';

const STAT_TINTS: Record<StatTint, { bubble: string; icon: string; ring: string }> = {
  primary: { bubble: 'bg-primary/10', icon: 'text-primary', ring: 'ring-primary/10' },
  emerald: { bubble: 'bg-emerald-500/10', icon: 'text-emerald-600 dark:text-emerald-400', ring: 'ring-emerald-500/10' },
  blue: { bubble: 'bg-blue-500/10', icon: 'text-blue-600 dark:text-blue-400', ring: 'ring-blue-500/10' },
  violet: { bubble: 'bg-violet-500/10', icon: 'text-violet-600 dark:text-violet-400', ring: 'ring-violet-500/10' },
};

function StatCard({ icon, label, value, tint }: { icon: React.ReactNode; label: string; value: string; tint: StatTint }) {
  const s = STAT_TINTS[tint];
  return (
    <div className={cn(
      'group relative overflow-hidden rounded-xl border border-border/60 bg-card px-4 py-3.5 shadow-sm ring-1 ring-transparent transition-all hover:-translate-y-0.5 hover:shadow-md',
      s.ring,
    )}>
      <div className='flex items-start gap-3'>
        <div className={cn('flex size-10 shrink-0 items-center justify-center rounded-lg', s.bubble, s.icon)}>
          {icon}
        </div>
        <div className='min-w-0 flex-1'>
          <p className='truncate text-[11px] font-medium uppercase tracking-wide text-muted-foreground'>{label}</p>
          <p className='mt-0.5 truncate text-xl font-bold leading-tight tabular-nums text-foreground'>{value}</p>
        </div>
      </div>
    </div>
  );
}

// ── Filters ──────────────────────────────────────────────────────────────────

const CONTENT_TYPE_TABS = [
  { value: '', label: 'Tất cả', icon: <Database className='size-3' /> },
  { value: 'group_post', label: 'Group Post', icon: <Newspaper className='size-3' /> },
  { value: 'comment', label: 'Comment', icon: <MessageCircle className='size-3' /> },
] as const;

interface FiltersProps {
  search: string;
  onSearchChange: (v: string) => void;
  campaignId: string;
  onCampaignIdChange: (v: string) => void;
  platform: string;
  onPlatformChange: (v: string) => void;
  contentType: string;
  onContentTypeChange: (v: string) => void;
  onRefresh: () => void;
  onApply: () => void;
  loading: boolean;
}

function Filters({ search, onSearchChange, campaignId, onCampaignIdChange, platform, onPlatformChange, contentType, onContentTypeChange, onRefresh, onApply, loading }: FiltersProps) {
  const onKeyEnter = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') onApply();
  };
  return (
    <div className='space-y-3'>
      {/* Content type tabs */}
      <div className='flex items-center gap-1 rounded-lg bg-muted/50 p-1'>
        {CONTENT_TYPE_TABS.map((tab) => (
          <button
            key={tab.value}
            type='button'
            onClick={() => onContentTypeChange(tab.value)}
            className={cn(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all',
              contentType === tab.value
                ? 'bg-background text-foreground shadow-sm ring-1 ring-border/60'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Search + filters + actions in one row */}
      <div className='flex flex-wrap items-center gap-2'>
        <div className='relative min-w-[200px] flex-1'>
          <Search className='pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground' />
          <Input
            className='h-9 pl-8 text-xs'
            placeholder='Tìm kiếm nội dung…'
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            onKeyDown={onKeyEnter}
          />
        </div>
        <Input
          className='h-9 w-44 text-xs'
          placeholder='Campaign ID…'
          value={campaignId}
          onChange={(e) => onCampaignIdChange(e.target.value)}
          onKeyDown={onKeyEnter}
        />
        <Input
          className='h-9 w-36 text-xs'
          placeholder='Platform…'
          value={platform}
          onChange={(e) => onPlatformChange(e.target.value)}
          onKeyDown={onKeyEnter}
        />
        <Button size='sm' variant='outline' className='h-9 gap-1.5 text-xs' onClick={onRefresh} disabled={loading}>
          <RefreshCw className={cn('size-3.5', loading && 'animate-spin')} />
          Tải lại
        </Button>
        <Button size='sm' className='h-9 gap-1.5 text-xs' onClick={onApply}>
          <Search className='size-3.5' />
          Áp dụng bộ lọc
        </Button>
      </div>
    </div>
  );
}

// ── Table (Tất cả / Post) ─────────────────────────────────────────────────────

const PLATFORM_STYLES: Record<string, string> = {
  facebook: 'bg-blue-500/10 text-blue-700 ring-blue-500/20 dark:text-blue-300',
  instagram: 'bg-pink-500/10 text-pink-700 ring-pink-500/20 dark:text-pink-300',
  tiktok: 'bg-neutral-900/10 text-neutral-900 ring-neutral-900/20 dark:bg-neutral-50/10 dark:text-neutral-100',
  twitter: 'bg-sky-500/10 text-sky-700 ring-sky-500/20 dark:text-sky-300',
  x: 'bg-sky-500/10 text-sky-700 ring-sky-500/20 dark:text-sky-300',
  youtube: 'bg-red-500/10 text-red-700 ring-red-500/20 dark:text-red-300',
};

function PlatformBadge({ name }: { name: string }) {
  const key = (name || '').toLowerCase();
  const cls = PLATFORM_STYLES[key] ?? 'bg-muted text-muted-foreground ring-border';
  return (
    <span className={cn(
      'inline-flex h-5 items-center rounded-md px-1.5 text-[10px] font-semibold ring-1 ring-inset',
      cls,
    )}>
      {name}
    </span>
  );
}

function EmptyState() {
  return (
    <div className='flex flex-col items-center justify-center rounded-xl border border-dashed border-border/60 py-20 text-center'>
      <div className='mb-3 flex size-14 items-center justify-center rounded-full bg-muted/60'>
        <Database className='size-7 text-muted-foreground/60' strokeWidth={1.5} />
      </div>
      <p className='text-sm font-semibold text-foreground'>Chưa có dữ liệu</p>
      <p className='mt-1 max-w-xs text-xs text-muted-foreground/80'>
        Chạy kịch bản có bước extract để thu thập dữ liệu từ các nền tảng.
      </p>
    </div>
  );
}

function ContentTable({
  items,
  onViewItem,
  onDeleteItem,
  onViewParent,
}: {
  items: ContentItem[];
  onViewItem: (item: ContentItem) => void;
  onDeleteItem: (id: string) => void;
  onViewParent: (parentId: string) => void;
}) {
  if (items.length === 0) return <EmptyState />;
  return (
    <div className='overflow-x-auto rounded-xl border border-border/60 bg-card shadow-sm'>
      <table className='w-full text-xs'>
        <thead>
          <tr className='border-b border-border/60 bg-muted/30 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground'>
            <th className='px-4 py-3 text-left'>Thời gian</th>
            <th className='px-4 py-3 text-left'>Platform / Type</th>
            <th className='px-4 py-3 text-left'>Nội dung</th>
            <th className='px-4 py-3 text-left'>Tác giả</th>
            <th className='px-4 py-3 text-right'>Tương tác</th>
            <th className='px-4 py-3 text-left'>Collection</th>
            <th className='w-20 px-4 py-3' />
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => (
            <tr
              key={item.id}
              className={cn(
                'group border-b border-border/40 transition-colors last:border-b-0',
                idx % 2 === 1 && 'bg-muted/10',
                'hover:bg-primary/[0.04]',
              )}
            >
              <td className='whitespace-nowrap px-4 py-3 align-top font-mono text-[10px] text-muted-foreground'>
                {item.extracted_at ? new Date(item.extracted_at).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' }) : '–'}
              </td>
              <td className='px-4 py-3 align-top'>
                <div className='flex flex-col items-start gap-1'>
                  {item.platform && <PlatformBadge name={item.platform} />}
                  <span className='text-[10px] font-medium text-muted-foreground'>{item.content_type}</span>
                  {item.parent_id && (
                    <button
                      type='button'
                      onClick={() => onViewParent(item.parent_id!)}
                      className='flex items-center gap-0.5 rounded px-1 py-0.5 text-[9px] text-blue-600 transition-colors hover:bg-blue-500/10 hover:underline dark:text-blue-400'
                    >
                      <FileText size={9} /> Bài gốc
                    </button>
                  )}
                </div>
              </td>
              <td className='max-w-[340px] px-4 py-3 align-top'>
                <p className='line-clamp-2 leading-snug text-foreground/90'>{item.title || item.body || <span className='italic text-muted-foreground'>(trống)</span>}</p>
                {item.url && (
                  <a
                    href={item.url}
                    target='_blank'
                    rel='noopener noreferrer'
                    className='mt-1 inline-flex items-center gap-1 text-[10px] text-primary/75 hover:text-primary hover:underline'
                    onClick={(e) => e.stopPropagation()}
                  >
                    <ExternalLink size={10} />
                    <span className='max-w-[240px] truncate'>{item.url}</span>
                  </a>
                )}
              </td>
              <td className='px-4 py-3 align-top text-foreground/80'>{item.author || <span className='text-muted-foreground'>–</span>}</td>
              <td className='whitespace-nowrap px-4 py-3 text-right align-top font-mono text-[11px] text-muted-foreground'>
                {[item.likes_count, item.comments_count, item.shares_count].filter((v) => v != null).join(' / ') || '–'}
              </td>
              <td className='px-4 py-3 align-top'>
                <span className='inline-flex items-center rounded-md border border-border/60 bg-background px-2 py-0.5 text-[10px] font-medium text-foreground/80'>
                  {item.collection}
                </span>
              </td>
              <td className='px-4 py-3 align-top'>
                <div className='flex items-center justify-end gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100'>
                  <Button size='sm' variant='ghost' className='h-7 w-7 p-0' onClick={() => onViewItem(item)} title='Xem chi tiết'>
                    <Eye size={13} />
                  </Button>
                  <Button size='sm' variant='ghost' className='h-7 w-7 p-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive' onClick={() => onDeleteItem(item.id)} title='Xoá'>
                    <Trash2 size={13} />
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Card feed (Comment) ───────────────────────────────────────────────────────

function ContentFeed({
  items,
  onViewItem,
  onDeleteItem,
  onViewParent,
}: {
  items: ContentItem[];
  onViewItem: (item: ContentItem) => void;
  onDeleteItem: (id: string) => void;
  onViewParent: (parentId: string) => void;
}) {
  if (items.length === 0) return <EmptyState />;

  return (
    <div className='space-y-3'>
      {items.map((item) => (
        <ContentCard
          key={item.id}
          item={item}
          onView={() => onViewItem(item)}
          onDelete={() => onDeleteItem(item.id)}
          onViewParent={item.parent_id ? () => onViewParent(item.parent_id!) : undefined}
        />
      ))}
    </div>
  );
}

function ContentCard({ item, onView, onDelete, onViewParent }: {
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
    ? new Date(item.extracted_at).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' })
    : '';

  const initials = item.author
    ? item.author.split(' ').map((w) => w[0]).slice(0, 2).join('').toUpperCase()
    : '?';

  return (
    <div className={cn(
      'group relative rounded-xl border bg-card transition-colors hover:border-border',
      isComment
        ? 'ml-6 border-l-2 border-l-blue-400/60 border-border/40 bg-blue-500/[0.02]'
        : 'border-border/50',
    )}>
      {/* Comment indent indicator */}
      {isComment && (
        <div className='absolute -left-6 top-4 flex items-center text-blue-400/60'>
          <CornerDownRight size={14} />
        </div>
      )}

      <div className='p-4'>
        {/* Header */}
        <div className='mb-2.5 flex items-start justify-between gap-3'>
          <div className='flex items-center gap-2.5'>
            {/* Avatar */}
            <div className={cn(
              'flex size-8 shrink-0 items-center justify-center rounded-full text-[11px] font-bold',
              isComment ? 'bg-blue-500/15 text-blue-600 dark:text-blue-400' : 'bg-primary/15 text-primary',
            )}>
              {initials}
            </div>
            <div>
              <div className='flex items-center gap-1.5'>
                <span className='text-sm font-semibold text-foreground'>{item.author || 'Ẩn danh'}</span>
                {item.platform && (
                  <Badge variant='secondary' className='h-4 px-1 text-[9px]'>{item.platform}</Badge>
                )}
                {isComment && (
                  <Badge className='h-4 bg-blue-500/15 px-1 text-[9px] text-blue-600 hover:bg-blue-500/15 dark:text-blue-400'>
                    comment
                  </Badge>
                )}
              </div>
              <div className='flex items-center gap-1 text-[10px] text-muted-foreground'>
                <Clock size={9} />
                <span>{time}</span>
                {item.collection && (
                  <>
                    <span>·</span>
                    <span className='rounded bg-muted px-1'>{item.collection}</span>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className='flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100'>
            {onViewParent && (
              <Button size='sm' variant='ghost' className='h-6 gap-1 px-2 text-[10px] text-blue-600' onClick={onViewParent}>
                <FileText size={10} /> Bài gốc
              </Button>
            )}
            <Button size='sm' variant='ghost' className='h-6 w-6 p-0' onClick={onView}>
              <Eye size={11} />
            </Button>
            <Button size='sm' variant='ghost' className='h-6 w-6 p-0 hover:text-destructive' onClick={onDelete}>
              <Trash2 size={11} />
            </Button>
          </div>
        </div>

        {/* Body */}
        {body && (
          <div className='mb-2.5'>
            <p className='whitespace-pre-wrap text-sm leading-relaxed text-foreground/90'>{displayBody}</p>
            {isLong && (
              <button
                type='button'
                onClick={() => setExpanded((v) => !v)}
                className='mt-0.5 text-[11px] text-primary hover:underline'
              >
                {expanded ? 'Thu gọn' : 'Xem thêm'}
              </button>
            )}
          </div>
        )}

        {/* URL */}
        {item.url && (
          <a
            href={item.url}
            target='_blank'
            rel='noopener noreferrer'
            className='mb-2.5 flex items-center gap-1 truncate text-[11px] text-primary/70 hover:text-primary'
          >
            <ExternalLink size={10} className='shrink-0' />
            <span className='truncate'>{item.url}</span>
          </a>
        )}

        {/* Engagement */}
        {(item.likes_count != null || item.comments_count != null || item.shares_count != null) && (
          <div className='flex items-center gap-3 border-t border-border/30 pt-2 text-[11px] text-muted-foreground'>
            {item.likes_count != null && (
              <span className='flex items-center gap-1'>
                <ThumbsUp size={11} className='text-blue-400' />
                {item.likes_count.toLocaleString()}
              </span>
            )}
            {item.comments_count != null && (
              <span className='flex items-center gap-1'>
                <MessageCircle size={11} className='text-green-500' />
                {item.comments_count.toLocaleString()}
              </span>
            )}
            {item.shares_count != null && (
              <span className='flex items-center gap-1'>
                <Share2 size={11} className='text-violet-400' />
                {item.shares_count.toLocaleString()}
              </span>
            )}
            {item.likes_count == null && item.shares_count == null && item.views_count != null && (
              <span className='flex items-center gap-1'>
                <Heart size={11} className='text-red-400' />
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

function Pagination({ page, totalPages, total, pageSize, onPageChange }: {
  page: number; totalPages: number; total: number; pageSize: number; onPageChange: (p: number) => void;
}) {
  if (totalPages <= 1) return null;
  const from = page * pageSize + 1;
  const to = Math.min((page + 1) * pageSize, total);
  return (
    <div className='flex items-center justify-between'>
      <p className='text-xs text-muted-foreground'>{from}–{to} / {total.toLocaleString()} bản ghi</p>
      <div className='flex items-center gap-1'>
        <Button size='sm' variant='outline' className='h-7 w-7 p-0' onClick={() => onPageChange(page - 1)} disabled={page === 0}>
          <ChevronLeft size={14} />
        </Button>
        <span className='px-2 text-xs text-muted-foreground'>Trang {page + 1} / {totalPages}</span>
        <Button size='sm' variant='outline' className='h-7 w-7 p-0' onClick={() => onPageChange(page + 1)} disabled={page >= totalPages - 1}>
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
  const [platform, setPlatform] = useState('');
  const [contentType, setContentType] = useState('');
  const [viewingItem, setViewingItem] = useState<ContentItem | null>(null);
  const [exporting, setExporting] = useState(false);

  const { items, total, page, totalPages, loading, error, filters, applyFilters, setPage, deleteItem, reload } = useContent({
    campaign_id: defaultCampaignId || undefined,
  });

  const handleExport = (format: ExportFormat) => {
    setExporting(true);
    try {
      contentApi.exportStream(filters, format);
    } finally {
      // brief delay so spinner is visible
      setTimeout(() => setExporting(false), 1200);
    }
  };

  const handleApply = (overrides?: { contentType?: string }) => {
    const ct = overrides?.contentType !== undefined ? overrides.contentType : contentType;
    applyFilters({
      search: search || undefined,
      campaign_id: campaignId || undefined,
      platform: platform || undefined,
      content_type: ct || undefined,
    });
  };

  const handleViewParent = (parentId: string) => {
    // Filter to show only the parent post (whose content_hash == parentId)
    applyFilters({ content_hash: parentId });
    setSearch('');
    setCampaignId('');
    setPlatform('');
    setContentType('');
  };

  const handleContentTypeChange = (v: string) => {
    setContentType(v);
    handleApply({ contentType: v });
  };

return (
    <div className='space-y-5'>
      <StatsBar />

      <div className='overflow-hidden rounded-2xl border border-border/60 bg-card shadow-sm'>
        {/* Header */}
        <div className='flex flex-wrap items-center justify-between gap-3 border-b border-border/60 bg-gradient-to-b from-muted/30 to-transparent px-5 py-4'>
          <div>
            <p className='text-base font-semibold leading-tight text-foreground'>Dữ liệu đã thu thập</p>
            <p className='mt-0.5 text-xs text-muted-foreground'>
              Tất cả nội dung được cào từ các lần chạy kịch bản
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Badge variant='secondary' className='h-7 rounded-full px-3 text-xs font-semibold tabular-nums'>
              {total.toLocaleString()} bản ghi
            </Badge>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size='sm' variant='outline' className='h-9 gap-1.5 text-xs' disabled={exporting || total === 0}>
                  {exporting
                    ? <RefreshCw className='size-3.5 animate-spin' />
                    : <Download className='size-3.5' />}
                  Export
                  <ChevronDown className='size-3' />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align='end'>
                <DropdownMenuItem onClick={() => handleExport('csv')}>
                  <FileText className='mr-2 size-3.5' />
                  CSV (streaming)
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => handleExport('xlsx')}>
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
            onSearchChange={(v) => { setSearch(v); }}
            campaignId={campaignId}
            onCampaignIdChange={(v) => { setCampaignId(v); }}
            platform={platform}
            onPlatformChange={(v) => { setPlatform(v); }}
            contentType={contentType}
            onContentTypeChange={handleContentTypeChange}
            onRefresh={() => { handleApply(); reload(); }}
            onApply={() => handleApply()}
            loading={loading}
          />
        </div>

        {/* Content */}
        <div className='p-5'>
          {error ? (
            <p className='rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive'>{error}</p>
          ) : loading ? (
            <div className='flex flex-col items-center justify-center gap-2 py-20'>
              <RefreshCw className='size-6 animate-spin text-muted-foreground/70' />
              <p className='text-xs text-muted-foreground'>Đang tải dữ liệu…</p>
            </div>
          ) : contentType === 'comment' ? (
            <ContentFeed items={items} onViewItem={setViewingItem} onDeleteItem={deleteItem} onViewParent={handleViewParent} />
          ) : (
            <ContentTable items={items} onViewItem={setViewingItem} onDeleteItem={deleteItem} onViewParent={handleViewParent} />
          )}
        </div>

        {/* Pagination */}
        {!loading && total > 0 && (
          <div className='border-t border-border/60 bg-muted/10 px-5 py-3'>
            <Pagination page={page} totalPages={totalPages} total={total} pageSize={50} onPageChange={setPage} />
          </div>
        )}
      </div>

      <ContentDetailDialog item={viewingItem} onClose={() => setViewingItem(null)} onViewParent={handleViewParent} />
    </div>
  );
}
