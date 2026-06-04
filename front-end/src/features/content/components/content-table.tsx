'use client';

import { useTranslations, useLocale } from 'next-intl';
import {
  CornerDownRight,
  ExternalLink,
  Eye,
  FileText,
  Trash2
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import {
  commentParentSummary,
  type CommentParentLabels
} from '../lib/comment-parent';
import {
  resolveCommentDisplayAuthor,
  resolveCommentDisplayBody
} from '../lib/comment-display';
import type { ContentItem } from '../services/api';

function useCommentParentLabels(): CommentParentLabels {
  const t = useTranslations('contentFeature.detail');
  return {
    fallbackTitle: t('parentFallbackTitle'),
    linkedTitle: t('parentLinkedTitle'),
    postIdLabel: (shortId) => t('parentPostIdLabel', { id: shortId })
  };
}

function CommentParentLine({
  item,
  onViewParent
}: {
  item: ContentItem;
  onViewParent?: (parentId: string) => void;
}) {
  const tList = useTranslations('contentFeature.list');
  const parentLabels = useCommentParentLabels();
  if (item.content_type !== 'fb_comment' && item.item_level <= 0) return null;
  const summary = commentParentSummary(item, parentLabels);
  if (!summary) return null;
  const content = (
    <>
      <div className='flex min-w-0 flex-wrap items-center gap-1.5'>
        <span className='font-semibold text-blue-700 dark:text-blue-300'>
          {tList('commentBelongsToPost')}
        </span>
        <span className='min-w-0 truncate font-medium text-foreground'>
          {summary.primary}
        </span>
        {summary.source ? (
          <span className='rounded bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:text-blue-300'>
            {summary.source === 'post_detail'
              ? tList('parentVerifiedShort')
              : summary.source}
          </span>
        ) : null}
      </div>
      {summary.secondary ? (
        <span className='block max-w-full truncate text-foreground/70'>
          {summary.secondary}
        </span>
      ) : null}
      {summary.postId ? (
        <span className='block max-w-full truncate font-mono text-[10px] text-muted-foreground'>
          {summary.postId}
        </span>
      ) : null}
    </>
  );
  const className =
    'mt-2 flex max-w-full items-start gap-2 rounded-md border border-blue-500/20 bg-blue-500/[0.04] px-2.5 py-2 text-[11px] leading-snug transition-colors';

  if (summary.linkedParentId && onViewParent) {
    return (
      <button
        type='button'
        onClick={(e) => {
          e.stopPropagation();
          onViewParent(summary.linkedParentId!);
        }}
        className={cn(
          className,
          'w-full cursor-pointer text-left hover:border-blue-500/35 hover:bg-blue-500/[0.08]'
        )}
      >
        <CornerDownRight size={13} className='mt-0.5 shrink-0 text-blue-500' />
        <div className='min-w-0'>{content}</div>
      </button>
    );
  }

  return (
    <div className={cn(className, 'text-muted-foreground')}>
      <CornerDownRight size={13} className='mt-0.5 shrink-0 text-blue-500' />
      <div className='min-w-0'>{content}</div>
    </div>
  );
}

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

export type ContentTableProps = {
  items: ContentItem[];
  onViewItem: (item: ContentItem) => void;
  onDeleteItem: (id: string) => void;
  onViewParent: (parentId: string) => void;
  canDelete?: boolean;
  /** Skip outer card border (e.g. inside post detail section). */
  embedded?: boolean;
  /** Hide parent-post context row (e.g. comments listed under their post). */
  hideParentLine?: boolean;
};

export function ContentTable({
  items,
  onViewItem,
  onDeleteItem,
  onViewParent,
  canDelete = false,
  embedded = false,
  hideParentLine = false
}: ContentTableProps) {
  const t = useTranslations('contentFeature.list');
  const locale = useLocale();

  if (items.length === 0) return null;

  const table = (
    <Table className='text-sm'>
      <TableHeader className='bg-muted/50'>
        <TableRow className='hover:bg-transparent'>
          <TableHead className='px-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground'>
            {t('tableColTime')}
          </TableHead>
          <TableHead className='px-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground'>
            {t('tableColPlatform')}
          </TableHead>
          <TableHead className='px-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground'>
            {t('tableColContent')}
          </TableHead>
          <TableHead className='px-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground'>
            {t('tableColAuthor')}
          </TableHead>
          <TableHead className='px-4 text-right text-[11px] font-semibold uppercase tracking-wider text-muted-foreground'>
            {t('tableColEngagement')}
          </TableHead>
          <TableHead className='px-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground'>
            {t('tableColCollection')}
          </TableHead>
          <TableHead className='w-24 px-4 text-right text-[11px] font-semibold uppercase tracking-wider text-muted-foreground'>
            {t('tableColActions')}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item, idx) => (
          <TableRow
            key={item.id}
            className={cn(
              'group cursor-pointer',
              idx % 2 === 1 && 'bg-muted/10',
              'hover:bg-primary/[0.05]'
            )}
            onClick={() => onViewItem(item)}
          >
            <TableCell className='whitespace-nowrap px-4 py-3.5 align-top font-mono text-[11px] text-muted-foreground'>
              {item.extracted_at
                ? new Date(item.extracted_at).toLocaleString(locale, {
                    dateStyle: 'short',
                    timeStyle: 'short'
                  })
                : '–'}
            </TableCell>
            <TableCell className='px-4 py-3.5 align-top'>
              <div className='flex flex-col items-start gap-1'>
                {item.platform && <PlatformBadge name={item.platform} />}
                <span className='text-[11px] font-medium text-muted-foreground'>
                  {item.content_type}
                </span>
                {item.parent_id ? (
                  <button
                    type='button'
                    onClick={(e) => {
                      e.stopPropagation();
                      onViewParent(item.parent_id!);
                    }}
                    className='inline-flex cursor-pointer items-center gap-1 rounded px-1 py-0.5 text-[10px] font-medium text-blue-600 transition-colors hover:bg-blue-500/10 hover:underline dark:text-blue-400'
                  >
                    <FileText size={10} /> {t('openParentPost')}
                  </button>
                ) : null}
              </div>
            </TableCell>
            <TableCell className='max-w-[380px] px-4 py-3.5 align-top whitespace-normal'>
              <p className='line-clamp-3 whitespace-pre-wrap leading-snug text-foreground/90'>
                {resolveCommentDisplayBody(item) ||
                  item.title ||
                  item.body || (
                    <span className='italic text-muted-foreground'>
                      {t('emptyContent')}
                    </span>
                  )}
              </p>
              {item.url ? (
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
              ) : null}
              {!hideParentLine ? (
                <CommentParentLine item={item} onViewParent={onViewParent} />
              ) : null}
            </TableCell>
            <TableCell className='px-4 py-3.5 align-top whitespace-normal text-foreground/90'>
              {resolveCommentDisplayAuthor(item) || item.author || (
                <span className='text-muted-foreground'>–</span>
              )}
            </TableCell>
            <TableCell className='whitespace-nowrap px-4 py-3.5 text-right align-top font-mono text-xs text-muted-foreground'>
              {[item.likes_count, item.comments_count, item.shares_count]
                .filter((v) => v != null)
                .join(' / ') || '–'}
            </TableCell>
            <TableCell className='px-4 py-3.5 align-top whitespace-normal'>
              <span className='inline-flex items-center rounded-md border border-border/60 bg-background px-2 py-0.5 text-[11px] font-medium text-foreground/80'>
                {item.collection}
              </span>
            </TableCell>
            <TableCell className='px-4 py-3.5 align-top'>
              <div className='flex items-center justify-end gap-1 opacity-60 transition-opacity focus-within:opacity-100 group-hover:opacity-100'>
                <Button
                  size='sm'
                  variant='ghost'
                  className='h-8 w-8 p-0'
                  onClick={(e) => {
                    e.stopPropagation();
                    onViewItem(item);
                  }}
                  title={t('viewDetail')}
                  aria-label={t('viewDetail')}
                >
                  <Eye size={15} />
                </Button>
                {canDelete ? (
                  <Button
                    size='sm'
                    variant='ghost'
                    className='h-8 w-8 p-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive'
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteItem(item.id);
                    }}
                    title={t('delete')}
                    aria-label={t('delete')}
                  >
                    <Trash2 size={15} />
                  </Button>
                ) : null}
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );

  if (embedded) return table;

  return (
    <div className='overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm'>
      {table}
    </div>
  );
}
