'use client';

import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Check, ExternalLink, Link2, Loader2 } from 'lucide-react';
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
import { ArtifactPreview } from './artifact-preview';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { isImageArtifact } from '../../lib/artifact-url';

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

export function ContentDetailView({ contentId, shareToken }: Props) {
  const t = useTranslations('contentFeature.detail');
  const locale = useLocale();
  const router = useRouter();
  const { detail, loading, error, statusCode } = useContentDetail(
    contentId,
    shareToken
  );
  const { canCreate: canCreatePermalink } = useResourcePermissions('content');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [permalinkBusy, setPermalinkBusy] = useState(false);
  const [permalinkCopied, setPermalinkCopied] = useState(false);

  const artifacts = useMemo(
    () => (detail?.artifacts ?? []).filter((artifact) => !contentArtifactIsImage(artifact)),
    [detail?.artifacts]
  );
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

  return (
    <div className='space-y-6'>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <div className='space-y-3'>
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
                  <Link href={ROUTES.CONTENT.ROOT}>{t('breadcrumbContent')}</Link>
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

          <div className='flex flex-wrap items-center gap-2'>
            <h1 className='text-lg font-semibold tracking-tight'>
              {t('title')}
            </h1>
            <Badge variant='secondary' className='font-mono text-[11px]'>
              {contentTypeBadge(detail.platform, detail.content_type)}
            </Badge>
            {detail.collection ? (
              <Badge variant='outline'>{detail.collection}</Badge>
            ) : null}
          </div>
        </div>

        {canCreatePermalink ? (
          <Button
            type='button'
            variant='outline'
            size='sm'
            className='gap-1.5'
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

      <div className='grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]'>
        <section className='space-y-4'>
          <MetadataCard detail={detail} executionId={executionId} t={t} />
          <div className='rounded-lg border bg-card'>
            <div className='border-b px-4 py-3'>
              <h2 className='text-sm font-semibold'>{t('payloadTitle')}</h2>
              <p className='text-xs text-muted-foreground'>{t('payloadHint')}</p>
            </div>
            <ScrollArea className='h-[min(50vh,480px)]'>
              <pre className='p-4 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all'>
                {payloadJson}
              </pre>
            </ScrollArea>
          </div>
        </section>

        <section className='space-y-3'>
          <div className='flex items-center justify-between gap-2'>
            <h2 className='text-sm font-semibold'>{t('artifactsTitle')}</h2>
            <span className='text-xs text-muted-foreground'>
              {artifacts.length}
            </span>
          </div>

          {artifacts.length === 0 ? (
            <p className='rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground'>
              {t('artifactsEmpty')}
            </p>
          ) : (
            <>
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
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function MetadataCard({
  detail,
  executionId,
  t
}: {
  detail: ContentDetail;
  executionId: string | null;
  t: ReturnType<typeof useTranslations>;
}) {
  const rows: { label: string; value: React.ReactNode }[] = [
    {
      label: t('metaExtractedAt'),
      value: detail.extracted_at
        ? new Date(detail.extracted_at).toLocaleString()
        : '–'
    },
    { label: t('metaDevice'), value: detail.device_serial ?? '–' },
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
    { label: t('metaAuthor'), value: detail.author ?? '–' }
  ];

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
      <dl className='divide-y px-4'>
        {rows.map((row) => (
          <div
            key={row.label}
            className='grid grid-cols-[120px_1fr] gap-2 py-2.5 text-xs'
          >
            <dt className='text-muted-foreground'>{row.label}</dt>
            <dd className='min-w-0 text-foreground'>{row.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
