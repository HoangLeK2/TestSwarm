'use client';

import { useEffect, useMemo, useState } from 'react';
import { Loader2, MessageCircle } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useRouter } from '@/i18n/navigation';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ROUTES } from '@/config/routes';
import { ContentTable } from '../content-table';
import { resolveCommentDisplayBody } from '../../lib/comment-display';
import {
  contentApi,
  type ContentDetail,
  type ContentItem
} from '../../services/api';

const PAGE_SIZE = 100;

type Props = {
  post: ContentDetail;
};

function sortCommentsOldestFirst(items: ContentItem[]): ContentItem[] {
  return [...items].sort((a, b) => {
    const ta = a.extracted_at ? new Date(a.extracted_at).getTime() : 0;
    const tb = b.extracted_at ? new Date(b.extracted_at).getTime() : 0;
    return ta - tb || a.id.localeCompare(b.id);
  });
}

export function PostCommentsSection({ post }: Props) {
  const t = useTranslations('contentFeature.detail');
  const router = useRouter();
  const [comments, setComments] = useState<ContentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await contentApi.listChildren(post.id, {
          limit: PAGE_SIZE,
          offset: 0
        });
        if (cancelled) return;
        setComments(sortCommentsOldestFirst(res.items));
        setTotal(res.total);
      } catch {
        if (!cancelled) {
          setError(t('postCommentsLoadError'));
          setComments([]);
          setTotal(0);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [post.id]);

  const loadMore = async () => {
    if (loadingMore || comments.length >= total) return;
    setLoadingMore(true);
    try {
      const res = await contentApi.listChildren(post.id, {
        limit: PAGE_SIZE,
        offset: comments.length
      });
      setComments((prev) => sortCommentsOldestFirst([...prev, ...res.items]));
      setTotal(res.total);
    } finally {
      setLoadingMore(false);
    }
  };

  const visibleComments = useMemo(
    () =>
      comments.filter((c) => Boolean(resolveCommentDisplayBody(c).trim())),
    [comments]
  );

  const openDetail = (item: ContentItem) => {
    router.push(ROUTES.CONTENT.DETAIL(item.id));
  };

  const openParent = (parentId: string) => {
    router.push(ROUTES.CONTENT.DETAIL(parentId));
  };

  return (
    <div className='rounded-lg border bg-card shadow-sm'>
      <div className='flex items-center justify-between gap-2 border-b px-4 py-3'>
        <div className='flex items-center gap-2'>
          <MessageCircle className='size-4 text-blue-600 dark:text-blue-400' />
          <h2 className='text-sm font-semibold'>{t('postCommentsTitle')}</h2>
        </div>
        {!loading && total > 0 ? (
          <Badge variant='secondary' className='font-mono text-[11px]'>
            {t('postCommentsCount', { count: total })}
          </Badge>
        ) : null}
      </div>

      <div className='px-4 py-3'>
        {loading ? (
          <div className='flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground'>
            <Loader2 className='size-4 animate-spin' />
            {t('postCommentsLoading')}
          </div>
        ) : error ? (
          <p className='py-6 text-center text-sm text-destructive'>{error}</p>
        ) : visibleComments.length === 0 ? (
          <p className='py-6 text-center text-sm text-muted-foreground'>
            {t('postCommentsEmpty')}
          </p>
        ) : (
          <>
            <ContentTable
              embedded
              hideParentLine
              items={visibleComments}
              onViewItem={openDetail}
              onDeleteItem={() => {}}
              onViewParent={openParent}
            />
            {comments.length < total ? (
              <div className='pt-3 text-center'>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  disabled={loadingMore}
                  onClick={() => void loadMore()}
                >
                  {loadingMore ? (
                    <Loader2 className='size-3.5 animate-spin' />
                  ) : null}
                  {t('postCommentsLoadMore', {
                    loaded: comments.length,
                    total
                  })}
                </Button>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
