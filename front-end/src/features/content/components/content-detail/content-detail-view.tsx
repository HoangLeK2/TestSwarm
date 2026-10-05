'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  Check,
  ChevronDown,
  CornerDownRight,
  ExternalLink,
  FileText,
  Hash,
  Link2,
  Loader2,
  MessageCircle,
  Share2,
  ThumbsUp
} from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import { Link, useRouter } from '@/i18n/navigation';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator
} from '@/components/ui/breadcrumb';
import { ScrollArea } from '@/components/ui/scroll-area';
import { ROUTES } from '@/config/routes';
import { cn } from '@/lib/utils';
import { useContentDetail } from '../../hooks/use-content-detail';
import {
  contentApi,
  type ContentArtifact,
  type ContentDetail
} from '../../services/api';
import { buildContentPermalink } from '../../lib/permalink';
import {
  commentParentSummary,
  type CommentParentLabels
} from '../../lib/comment-parent';
import {
  resolveCommentDisplayAuthor,
  resolveCommentDisplayBody
} from '../../lib/comment-display';
import { ArtifactPreview } from './artifact-preview';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { isImageArtifact } from '../../lib/artifact-url';
import { shouldShowPostComments } from '../../lib/post-detail';
import { PostCommentsSection } from './post-comments-section';

type Props = {
  contentId: string;
  shareToken?: string | null;
};

function contentTypeBadge(platform: string | null, contentType: string) {
  if (platform) {
    return `${platform}:${contentType}`;
  }
  return contentType;
}

function contentArtifactIsImage(artifact: ContentArtifact): boolean {
  return isImageArtifact(artifact.kind, artifact.url, {
    label: artifact.label,
    mimeType: artifact.mime_type,
    source: artifact.source
  });
}

function parentContentHref(parentId: string): string {
  return ROUTES.CONTENT.BY_HASH(parentId);
}

function shortId(value: string, head = 8): string {
  const v = value.trim();
  if (v.length <= head + 1) return v;
  return `${v.slice(0, head)}…`;
}

function isCommentContent(detail: ContentDetail): boolean {
  return detail.content_type.endsWith('comment') || detail.item_level > 0;
}

export function ContentDetailView({ contentId, shareToken }: Props) {
  const t = useTranslations('contentFeature.detail');
  const locale = useLocale();
  const parentLabels: CommentParentLabels = useMemo(
    () => ({
      fallbackTitle: t('parentFallbackTitle'),
      linkedTitle: t('parentLinkedTitle'),
      postIdLabel: (shortId) => t('parentPostIdLabel', { id: shortId })
    }),
    [t]
  );
  const router = useRouter();
  const { detail, loading, error, statusCode } = useContentDetail(
    contentId,
    shareToken
  );
  const { canCreate: canCreatePermalink } = useResourcePermissions('content');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [permalinkBusy, setPermalinkBusy] = useState(false);
  const [permalinkCopied, setPermalinkCopied] = useState(false);
  const [payloadExpanded, setPayloadExpanded] = useState<boolean | null>(null);

  const imageArtifacts = useMemo(() => {
    if (!detail?.artifacts) return [];
    return detail.artifacts.filter(contentArtifactIsImage);
  }, [detail?.artifacts]);
  const artifacts = useMemo(() => {
    if (!detail?.artifacts) return [];
    return detail.artifacts.filter(
      (artifact) => !contentArtifactIsImage(artifact)
    );
  }, [detail?.artifacts]);
  const selected: ContentArtifact | null =
    artifacts.find((a) => a.id === selectedId) ?? artifacts[0] ?? null;

  const payloadJson = useMemo(() => {
    if (!detail?.payload) return '';
    return JSON.stringify(detail.payload, null, 2);
  }, [detail?.payload]);

  const handleCopyPermalink = async () => {
    if (!detail) return;
    setPermalinkBusy(true);
    try {
      const { token } = await contentApi.createPermalink(detail.id);
      const url = buildContentPermalink(
        window.location.origin,
        locale,
        detail.id,
        token
      );
      await navigator.clipboard.writeText(url);
      setPermalinkCopied(true);
      setTimeout(() => setPermalinkCopied(false), 2000);
    } finally {
      setPermalinkBusy(false);
    }
  };

  const handleOpenParentPost = async (parentId: string) => {
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
      // Fall back to the hash-filtered content page below.
    }
    router.push(parentContentHref(parentId));
  };

  useEffect(() => {
    if (!contentId) {
      router.replace(ROUTES.CONTENT.ROOT);
      return;
    }
    if (statusCode === 403 || statusCode === 404) {
      router.replace(ROUTES.ERROR.FORBIDDEN);
    }
  }, [contentId, router, statusCode]);

  if (loading) {
    return (
      <div className='flex min-h-[40vh] items-center justify-center gap-2 text-muted-foreground'>
        <Loader2 className='size-5 animate-spin' />
        {t('loading')}
      </div>
    );
  }

  if (statusCode === 403 || statusCode === 404) {
    return null;
  }

  if (error || !detail) {
    return (
      <div className='rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive'>
        {error ?? t('loadError')}
      </div>
    );
  }

  const executionId = detail.execution_id ?? detail.run_id ?? null;
  const extractedLabel = detail.extracted_at
    ? new Date(detail.extracted_at).toLocaleString(locale)
    : null;
  const displayBody = resolveCommentDisplayBody(detail);
  const displayAuthor = resolveCommentDisplayAuthor(detail);
  const hasReadableBody = Boolean(displayBody.trim());
  const showPayload =
    payloadExpanded ?? (!hasReadableBody || !payloadJson.trim());
  const isComment = isCommentContent(detail);
  const showPostComments = shouldShowPostComments(detail);
  const parentSummary = isComment
    ? commentParentSummary(detail, parentLabels)
    : null;

  return (
    <div className='w-full min-w-0 space-y-5'>
      <div className='flex flex-wrap items-start justify-between gap-4'>
        <div className='min-w-0 flex-1 space-y-3'>
          <Button
            type='button'
            variant='ghost'
            size='sm'
            className='-ml-2 h-8 gap-1'
            onClick={() => router.push(ROUTES.CONTENT.ROOT)}
          >
            <ArrowLeft className='size-4' />
            {t('backToList')}
          </Button>

          <Breadcrumb>
            <BreadcrumbList>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link href={ROUTES.CONTENT.ROOT}>
                    {t('breadcrumbContent')}
                  </Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              {detail.campaign_id ? (
                <>
                  <BreadcrumbItem>
                    <BreadcrumbLink asChild>
                      <Link href={ROUTES.CAMPAIGNS.DETAIL(detail.campaign_id)}>
                        {t('breadcrumbCampaign')}
                      </Link>
                    </BreadcrumbLink>
                  </BreadcrumbItem>
                  <BreadcrumbSeparator />
                </>
              ) : null}
              <BreadcrumbItem>
                <BreadcrumbPage className='max-w-[200px] truncate font-mono text-xs'>
                  {detail.id.slice(0, 8)}…
                </BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>

          <div className='space-y-1.5'>
            <div className='flex flex-wrap items-center gap-2'>
              <h1 className='text-xl font-semibold tracking-tight'>
                {t('title')}
              </h1>
              <Badge variant='secondary' className='font-mono text-[11px]'>
                {contentTypeBadge(detail.platform, detail.content_type)}
              </Badge>
              {detail.collection ? (
                <Badge variant='outline'>{detail.collection}</Badge>
              ) : null}
            </div>
            <p className='text-sm text-muted-foreground'>
              <span className='font-medium text-foreground'>
                {displayAuthor || t('anonymousAuthor')}
              </span>
              {extractedLabel ? (
                <>
                  <span className='mx-1.5 text-border'>·</span>
                  <time dateTime={detail.extracted_at ?? undefined}>
                    {extractedLabel}
                  </time>
                </>
              ) : null}
              <span className='mx-1.5 text-border'>·</span>
              <span
                className='font-mono text-xs'
                title={detail.content_hash || detail.id}
              >
                {shortId(detail.content_hash || detail.id)}
              </span>
            </p>
          </div>
        </div>

        {canCreatePermalink ? (
          <Button
            type='button'
            variant='outline'
            size='sm'
            className='shrink-0 gap-1.5'
            disabled={permalinkBusy}
            onClick={() => void handleCopyPermalink()}
          >
            {permalinkCopied ? (
              <Check className='size-4 text-emerald-500' />
            ) : (
              <Link2 className='size-4' />
            )}
            {permalinkCopied ? t('permalinkCopied') : t('copyPermalink')}
          </Button>
        ) : null}
      </div>

      <section className='grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,24rem)] lg:items-start'>
        <div className='min-w-0 space-y-4'>
          {isComment ? (
            <>
              <CommentEvidenceCard
                body={displayBody}
                author={displayAuthor}
                parentSummary={parentSummary}
                t={t}
                onOpenParent={(parentId) => void handleOpenParentPost(parentId)}
              />
              <ImageArtifacts
                detail={detail}
                artifacts={imageArtifacts}
                shareToken={shareToken}
              />
            </>
          ) : (
            <>
              <ContentBodyCard
                detail={detail}
                body={displayBody}
                author={displayAuthor}
                t={t}
              />
              <ImageArtifacts
                detail={detail}
                artifacts={imageArtifacts}
                shareToken={shareToken}
              />
              {showPostComments ? <PostCommentsSection post={detail} /> : null}
            </>
          )}
        </div>

        <aside className='flex min-w-0 flex-col gap-4 lg:sticky lg:top-4 lg:max-h-[calc(100dvh-6rem)] lg:overflow-y-auto lg:pr-1'>
          <MetadataCard
            detail={detail}
            executionId={executionId}
            showParentLink={!parentSummary}
            t={t}
          />
          <PayloadPanel
            payloadJson={payloadJson}
            open={showPayload}
            collapsible={hasReadableBody && Boolean(payloadJson.trim())}
            onOpenChange={setPayloadExpanded}
            t={t}
          />
        </aside>
      </section>

      {artifacts.length > 0 ? (
        <section className='space-y-3'>
          <div className='flex items-center justify-between gap-2'>
            <h2 className='text-sm font-semibold'>{t('artifactsTitle')}</h2>
            <span className='text-xs text-muted-foreground'>
              {artifacts.length}
            </span>
          </div>

          <div className='flex flex-wrap gap-2'>
            {artifacts.map((artifact) => (
              <button
                key={artifact.id}
                type='button'
                onClick={() => setSelectedId(artifact.id)}
                className={cn(
                  'rounded-full border px-3 py-1 text-xs transition',
                  selected?.id === artifact.id
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border bg-background hover:bg-muted/50'
                )}
              >
                {artifact.label}
              </button>
            ))}
          </div>
          {selected ? (
            <ArtifactPreview
              detail={detail}
              artifact={selected}
              shareToken={shareToken}
            />
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function ImageArtifacts({
  detail,
  artifacts,
  shareToken
}: {
  detail: ContentDetail;
  artifacts: ContentArtifact[];
  shareToken?: string | null;
}) {
  if (artifacts.length === 0) return null;
  return (
    <div className='space-y-3'>
      {artifacts.map((artifact) => (
        <ArtifactPreview
          key={artifact.id}
          detail={detail}
          artifact={artifact}
          shareToken={shareToken}
        />
      ))}
    </div>
  );
}

function ContentBodyCard({
  detail,
  body: bodyText,
  author: displayAuthor,
  t
}: {
  detail: ContentDetail;
  body: string;
  author: string | null;
  t: ReturnType<typeof useTranslations>;
}) {
  const [expanded, setExpanded] = useState(false);
  const title = detail.title?.trim() ?? '';
  const body = bodyText.trim();
  const isComment =
    detail.content_type.endsWith('comment') || detail.item_level > 0;

  if (!body) {
    return (
      <div className='rounded-lg border border-dashed bg-muted/20 px-4 py-8 text-center text-sm text-muted-foreground'>
        {t('noBodyText')}
      </div>
    );
  }

  const isLong = body.length > 400;
  const displayBody = isLong && !expanded ? `${body.slice(0, 400)}…` : body;

  const stats = [
    {
      icon: ThumbsUp,
      value: detail.likes_count,
      label: 'likes'
    },
    {
      icon: MessageCircle,
      value: detail.comments_count,
      label: 'comments'
    },
    {
      icon: Share2,
      value: detail.shares_count,
      label: 'shares'
    }
  ].filter((s) => s.value != null && s.value > 0);

  return (
    <div
      className={cn(
        'rounded-lg border bg-card shadow-sm',
        isComment && 'border-l-2 border-l-blue-400/70'
      )}
    >
      <div className='border-b px-4 py-3'>
        <h2 className='text-sm font-semibold'>{t('contentTitle')}</h2>
        {isComment && displayAuthor ? (
          <p className='mt-0.5 text-xs text-muted-foreground'>
            {displayAuthor}
          </p>
        ) : null}
      </div>
      <div className='space-y-3 px-4 py-4 lg:px-6 lg:py-5'>
        {title && title !== body ? (
          <p className='text-sm font-semibold text-foreground lg:text-base'>
            {title}
          </p>
        ) : null}
        <p className='whitespace-pre-wrap text-[15px] leading-relaxed text-foreground lg:text-base lg:leading-7'>
          {displayBody}
        </p>
        {isLong ? (
          <button
            type='button'
            onClick={() => setExpanded((v) => !v)}
            className='text-xs font-medium text-primary hover:underline'
          >
            {expanded ? t('showLess') : t('showMore')}
          </button>
        ) : null}
        {stats.length > 0 ? (
          <div className='flex flex-wrap gap-3 border-t border-border/60 pt-3 text-xs text-muted-foreground'>
            {stats.map(({ icon: Icon, value, label }) => (
              <span key={label} className='inline-flex items-center gap-1'>
                <Icon className='size-3.5' />
                {value?.toLocaleString()}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function PayloadPanel({
  payloadJson,
  open,
  collapsible,
  onOpenChange,
  t
}: {
  payloadJson: string;
  open: boolean;
  collapsible: boolean;
  onOpenChange: (open: boolean) => void;
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <div className='rounded-lg border bg-card'>
      <div className='flex items-start justify-between gap-2 border-b px-4 py-3'>
        <div className='min-w-0'>
          <h2 className='text-sm font-semibold'>{t('payloadTitle')}</h2>
          <p className='text-xs text-muted-foreground'>{t('payloadHint')}</p>
        </div>
        {collapsible ? (
          <Button
            type='button'
            variant='ghost'
            size='sm'
            className='shrink-0 gap-1 text-xs'
            onClick={() => onOpenChange(!open)}
          >
            {open ? t('payloadToggleCollapse') : t('payloadToggleExpand')}
            <ChevronDown
              className={cn(
                'size-3.5 transition-transform',
                open && 'rotate-180'
              )}
            />
          </Button>
        ) : null}
      </div>
      {open ? (
        <ScrollArea className='h-[min(40vh,420px)]'>
          <pre className='whitespace-pre-wrap break-all p-4 font-mono text-[11px] leading-relaxed'>
            {payloadJson || '{}'}
          </pre>
        </ScrollArea>
      ) : null}
    </div>
  );
}

function CommentEvidenceCard({
  body,
  author,
  parentSummary,
  t,
  onOpenParent
}: {
  body: string;
  author: string | null;
  parentSummary: ReturnType<typeof commentParentSummary>;
  t: ReturnType<typeof useTranslations>;
  onOpenParent: (parentId: string) => void;
}) {
  const bodyText = body.trim();
  const [expanded, setExpanded] = useState(false);
  const isLong = bodyText.length > 500;
  const displayBody =
    isLong && !expanded ? `${bodyText.slice(0, 500)}…` : bodyText;

  return (
    <div className='overflow-hidden rounded-lg border bg-card shadow-sm'>
      {parentSummary ? (
        <div className='border-b border-blue-500/20 bg-blue-500/[0.04] px-4 py-3'>
          <div className='flex items-start gap-3'>
            <div className='mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-blue-500/10 text-blue-600 dark:text-blue-300'>
              <CornerDownRight className='size-4' />
            </div>
            <div className='min-w-0 flex-1 space-y-1'>
              <div className='flex flex-wrap items-center gap-2'>
                <p className='text-xs font-medium uppercase tracking-wide text-muted-foreground'>
                  {t('parentPostTitle')}
                </p>
                {parentSummary.source ? (
                  <Badge
                    variant='secondary'
                    className='h-5 bg-blue-500/10 px-1.5 text-[10px] text-blue-700 dark:text-blue-300'
                  >
                    {parentSummary.source === 'post_detail'
                      ? t('parentPostVerified')
                      : parentSummary.source}
                  </Badge>
                ) : null}
              </div>
              <p className='text-sm font-semibold text-foreground'>
                {parentSummary.primary}
              </p>
              {parentSummary.secondary ? (
                <p className='line-clamp-3 text-sm leading-relaxed text-muted-foreground'>
                  {parentSummary.secondary}
                </p>
              ) : null}
              <div className='flex flex-wrap items-center gap-2 pt-1'>
                {parentSummary.linkedParentId ? (
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    className='h-7 gap-1 text-xs'
                    onClick={() => onOpenParent(parentSummary.linkedParentId!)}
                  >
                    <FileText className='size-3' />
                    {t('openParentPost')}
                  </Button>
                ) : null}
                {parentSummary.postId ? (
                  <span
                    className='inline-flex max-w-full items-center gap-1 rounded-md border border-border/60 bg-background px-2 py-1 font-mono text-[11px] text-muted-foreground'
                    title={parentSummary.postId}
                  >
                    <Hash className='size-3 shrink-0' />
                    {shortId(parentSummary.postId, 12)}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      <div className='px-4 py-4'>
        <p className='text-xs font-medium uppercase tracking-wide text-muted-foreground'>
          {t('commentBodyTitle')}
        </p>
        {author ? (
          <p className='mt-2 text-base font-semibold text-foreground'>
            {author}
          </p>
        ) : null}
        {bodyText ? (
          <>
            <p
              className={cn(
                'whitespace-pre-wrap leading-relaxed text-foreground',
                author ? 'mt-2 text-[15px]' : 'mt-2 text-base'
              )}
            >
              {displayBody}
            </p>
            {isLong ? (
              <button
                type='button'
                onClick={() => setExpanded((v) => !v)}
                className='mt-2 text-xs font-medium text-primary hover:underline'
              >
                {expanded ? t('showLess') : t('showMore')}
              </button>
            ) : null}
          </>
        ) : (
          <p className='mt-2 text-sm text-muted-foreground'>
            {t('noBodyText')}
          </p>
        )}
      </div>
    </div>
  );
}

function MetadataCard({
  detail,
  executionId,
  showParentLink,
  t
}: {
  detail: ContentDetail;
  executionId: string | null;
  showParentLink: boolean;
  t: ReturnType<typeof useTranslations>;
}) {
  const rows: { label: string; value: React.ReactNode }[] = [
    {
      label: t('metaExtractedAt'),
      value: detail.extracted_at
        ? new Date(detail.extracted_at).toLocaleString()
        : '–'
    },
    {
      label: t('metaDevice'),
      value: detail.device_serial ? (
        <span className='font-mono' title={detail.device_serial}>
          {shortId(detail.device_serial, 12)}
        </span>
      ) : (
        '–'
      )
    },
    {
      label: t('metaCampaign'),
      value: detail.campaign_id ? (
        <Link
          href={ROUTES.CAMPAIGNS.DETAIL(detail.campaign_id)}
          className='text-primary hover:underline'
        >
          {detail.campaign_id.slice(0, 8)}…
        </Link>
      ) : (
        '–'
      )
    },
    {
      label: t('metaExecution'),
      value: executionId ? (
        <Link
          href={ROUTES.CONTENT.BY_EXECUTION(executionId)}
          className='text-primary hover:underline'
        >
          {executionId.slice(0, 8)}…
        </Link>
      ) : (
        '–'
      )
    },
    { label: t('metaScenario'), value: detail.scenario_name ?? '–' },
    {
      label: t('metaAuthor'),
      value: resolveCommentDisplayAuthor(detail) ?? detail.author ?? '–'
    }
  ];

  const linkedParentHash = detail.parent_item_hash || detail.parent_id;
  if (showParentLink && linkedParentHash) {
    rows.push({
      label: t('metaParent'),
      value: (
        <Link
          href={parentContentHref(linkedParentHash)}
          title={linkedParentHash}
          className='inline-flex items-center gap-1 font-mono text-primary hover:underline'
        >
          <FileText className='size-3 shrink-0' />
          {shortId(linkedParentHash, 12)}
        </Link>
      )
    });
  }

  if (detail.url) {
    rows.push({
      label: t('metaUrl'),
      value: (
        <a
          href={detail.url}
          target='_blank'
          rel='noopener noreferrer'
          className='inline-flex items-center gap-1 break-all text-primary hover:underline'
        >
          <ExternalLink className='size-3 shrink-0' />
          {detail.url}
        </a>
      )
    });
  }

  return (
    <div className='rounded-lg border bg-card'>
      <div className='border-b px-4 py-3'>
        <h2 className='text-sm font-semibold'>{t('metadataTitle')}</h2>
      </div>
      <dl className='space-y-2.5 px-4 py-3'>
        {rows.map((row) => (
          <div key={row.label} className='min-w-0 space-y-0.5 text-xs'>
            <dt className='font-medium text-muted-foreground'>{row.label}</dt>
            <dd className='min-w-0 truncate text-foreground sm:overflow-visible sm:whitespace-normal'>
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
