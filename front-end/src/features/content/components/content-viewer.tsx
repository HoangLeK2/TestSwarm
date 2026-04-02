'use client';

import { useState } from 'react';
import {
  Search, RefreshCw, ChevronLeft, ChevronRight,
  Trash2, ExternalLink, Eye, Database, TrendingUp,
  Smartphone, FileText, MessageCircle, Newspaper,
  Heart, Share2, ThumbsUp, Clock, CornerDownRight,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { useContent, useContentStats } from '../hooks/use-content';
import type { ContentItem } from '../services/api';
import { ContentDetailDialog } from './content-detail-dialog';

// ── Stats bar ────────────────────────────────────────────────────────────────

function StatsBar() {
  const { stats } = useContentStats();
  if (!stats) return null;
  return (
    <div className='grid grid-cols-2 gap-3 sm:grid-cols-4'>
      <StatCard icon={<Database className='size-4 text-primary' />} label='Tổng bản ghi' value={stats.total_items.toLocaleString()} />
      <StatCard icon={<TrendingUp className='size-4 text-emerald-500' />} label='Platforms' value={Object.keys(stats.by_platform).length.toString()} />
      <StatCard icon={<FileText className='size-4 text-blue-500' />} label='Collections' value={Object.keys(stats.by_collection).length.toString()} />
      <StatCard
        icon={<Smartphone className='size-4 text-violet-500' />}
        label='Lần cào gần nhất'
        value={stats.latest_extraction ? new Date(stats.latest_extraction).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' }) : '–'}
      />
    </div>
  );
}

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className='flex items-center gap-3 rounded-lg border bg-card px-3 py-2.5'>
      <div className='shrink-0'>{icon}</div>
      <div className='min-w-0'>
        <p className='truncate text-[10px] text-muted-foreground'>{label}</p>
        <p className='truncate text-sm font-bold text-foreground'>{value}</p>
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
  loading: boolean;
}

function Filters({ search, onSearchChange, campaignId, onCampaignIdChange, platform, onPlatformChange, contentType, onContentTypeChange, onRefresh, loading }: FiltersProps) {
  return (
    <div className='space-y-2'>
      {/* Content type tabs */}
      <div className='flex items-center gap-1'>
        {CONTENT_TYPE_TABS.map((tab) => (
          <button
            key={tab.value}
            type='button'
            onClick={() => onContentTypeChange(tab.value)}
            className={cn(
              'flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors',
              contentType === tab.value
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-accent hover:text-foreground',
            )}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Search + other filters */}
      <div className='flex flex-wrap items-center gap-2'>
        <div className='relative min-w-[180px] flex-1'>
          <Search className='absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground' />
          <Input
            className='h-8 pl-8 text-xs'
            placeholder='Tìm kiếm nội dung…'
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
          />
        </div>
        <Input
          className='h-8 w-48 text-xs'
          placeholder='Campaign ID…'
          value={campaignId}
          onChange={(e) => onCampaignIdChange(e.target.value)}
        />
        <Input
          className='h-8 w-36 text-xs'
          placeholder='Platform…'
          value={platform}
          onChange={(e) => onPlatformChange(e.target.value)}
        />
        <Button size='sm' variant='outline' className='h-8 gap-1.5 text-xs' onClick={onRefresh} disabled={loading}>
          <RefreshCw className={cn('size-3', loading && 'animate-spin')} />
          Tải lại
        </Button>
      </div>
    </div>
  );
}

// ── Table (Tất cả / Post) ─────────────────────────────────────────────────────

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
  if (items.length === 0) {
    return (
      <div className='flex flex-col items-center justify-center rounded-xl border border-dashed border-border/50 py-20 text-center'>
        <Database className='mb-3 size-10 text-muted-foreground/30' strokeWidth={1.25} />
        <p className='text-sm font-medium text-muted-foreground'>Chưa có dữ liệu</p>
        <p className='mt-1 text-xs text-muted-foreground/60'>Chạy kịch bản có bước extract để thu thập dữ liệu</p>
      </div>
    );
  }
  return (
    <div className='overflow-x-auto rounded-lg border border-border/50'>
      <table className='w-full text-xs'>
        <thead>
          <tr className='border-b bg-muted/40 text-[11px] font-semibold text-muted-foreground'>
            <th className='px-3 py-2 text-left'>Thời gian</th>
            <th className='px-3 py-2 text-left'>Platform / Type</th>
            <th className='px-3 py-2 text-left'>Nội dung</th>
            <th className='px-3 py-2 text-left'>Tác giả</th>
            <th className='px-3 py-2 text-right'>Tương tác</th>
            <th className='px-3 py-2 text-left'>Collection</th>
            <th className='w-16 px-3 py-2' />
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} className='group border-b border-border/40 transition-colors hover:bg-muted/30'>
              <td className='whitespace-nowrap px-3 py-2 font-mono text-[10px] text-muted-foreground'>
                {item.extracted_at ? new Date(item.extracted_at).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' }) : '–'}
              </td>
              <td className='px-3 py-2'>
                <div className='flex flex-col gap-0.5'>
                  {item.platform && <Badge variant='secondary' className='h-4 w-fit px-1 text-[9px]'>{item.platform}</Badge>}
                  <span className='text-[10px] text-muted-foreground'>{item.content_type}</span>
                  {item.parent_id && (
                    <button type='button' onClick={() => onViewParent(item.parent_id!)}
                      className='flex items-center gap-0.5 text-[9px] text-blue-600 hover:underline dark:text-blue-400'>
                      <FileText size={9} /> Bài gốc
                    </button>
                  )}
                </div>
              </td>
              <td className='max-w-[300px] px-3 py-2'>
                <p className='truncate text-foreground/90'>{item.title || item.body || '(trống)'}</p>
                {item.url && (
                  <a href={item.url} target='_blank' rel='noopener noreferrer'
                    className='flex items-center gap-0.5 text-[10px] text-primary/70 hover:text-primary' onClick={(e) => e.stopPropagation()}>
                    <ExternalLink size={9} /><span className='max-w-[200px] truncate'>{item.url}</span>
                  </a>
                )}
              </td>
              <td className='px-3 py-2 text-muted-foreground'>{item.author || '–'}</td>
              <td className='whitespace-nowrap px-3 py-2 text-right font-mono text-[10px] text-muted-foreground'>
                {[item.likes_count, item.comments_count, item.shares_count].filter((v) => v != null).join(' / ') || '–'}
              </td>
              <td className='px-3 py-2'>
                <span className='rounded bg-muted px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground'>{item.collection}</span>
              </td>
              <td className='px-3 py-2'>
                <div className='flex items-center justify-end gap-1 opacity-0 transition-opacity group-hover:opacity-100'>
                  <Button size='sm' variant='ghost' className='h-6 w-6 p-0' onClick={() => onViewItem(item)}><Eye size={11} /></Button>
                  <Button size='sm' variant='ghost' className='h-6 w-6 p-0 hover:text-destructive' onClick={() => onDeleteItem(item.id)}><Trash2 size={11} /></Button>
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
  if (items.length === 0) {
    return (
      <div className='flex flex-col items-center justify-center rounded-xl border border-dashed border-border/50 py-20 text-center'>
        <Database className='mb-3 size-10 text-muted-foreground/30' strokeWidth={1.25} />
        <p className='text-sm font-medium text-muted-foreground'>Chưa có dữ liệu</p>
        <p className='mt-1 text-xs text-muted-foreground/60'>Chạy kịch bản có bước extract để thu thập dữ liệu</p>
      </div>
    );
  }

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

  const { items, total, page, totalPages, loading, error, applyFilters, setPage, deleteItem, reload } = useContent({
    campaign_id: defaultCampaignId || undefined,
  });

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
    <div className='space-y-4'>
      <StatsBar />

      <div className='rounded-xl border border-border/50 bg-card'>
        {/* Header */}
        <div className='flex items-center justify-between border-b border-border/40 px-4 py-3'>
          <div>
            <p className='text-sm font-semibold text-foreground'>Dữ liệu đã thu thập</p>
            <p className='text-[11px] text-muted-foreground'>
              Tất cả nội dung được cào từ các lần chạy kịch bản
            </p>
          </div>
          <Badge variant='secondary' className='text-xs'>{total.toLocaleString()} bản ghi</Badge>
        </div>

        {/* Filters */}
        <div className='border-b border-border/40 px-4 py-3'>
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
            loading={loading}
          />
          <div className='mt-2 flex justify-end'>
            <Button size='sm' className='h-7 text-xs' onClick={() => handleApply()}>
              Áp dụng bộ lọc
            </Button>
          </div>
        </div>

        {/* Content */}
        <div className='p-4'>
          {error ? (
            <p className='rounded bg-destructive/10 px-3 py-2 text-xs text-destructive'>{error}</p>
          ) : loading ? (
            <div className='flex items-center justify-center py-16'>
              <RefreshCw className='size-5 animate-spin text-muted-foreground' />
            </div>
          ) : contentType === 'comment' ? (
            <ContentFeed items={items} onViewItem={setViewingItem} onDeleteItem={deleteItem} onViewParent={handleViewParent} />
          ) : (
            <ContentTable items={items} onViewItem={setViewingItem} onDeleteItem={deleteItem} onViewParent={handleViewParent} />
          )}
        </div>

        {/* Pagination */}
        {!loading && total > 0 && (
          <div className='border-t border-border/40 px-4 py-3'>
            <Pagination page={page} totalPages={totalPages} total={total} pageSize={50} onPageChange={setPage} />
          </div>
        )}
      </div>

      <ContentDetailDialog item={viewingItem} onClose={() => setViewingItem(null)} onViewParent={handleViewParent} />
    </div>
  );
}
