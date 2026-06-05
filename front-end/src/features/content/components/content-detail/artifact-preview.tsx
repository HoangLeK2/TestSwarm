'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Download, Loader2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  contentApi,
  type ContentArtifact,
  type ContentDetail
} from '../../services/api';
import { deviceFarmBackendBase } from '@/lib/farm-api';
import { triggerBlobDownload } from '../../lib/download';
import {
  directObjectStorageUrl,
  isImageArtifact,
  resolveArtifactUrl,
  shouldProxyArtifactFetch
} from '../../lib/artifact-url';

const PREVIEW_LINE_LIMIT = 400;
const LARGE_INLINE_BYTES = 256_000;
const VIRTUAL_LINE_HEIGHT_PX = 16;
const VIRTUAL_VIEWPORT_LINES = 32;
const CONTENT_IMAGE_PREVIEW_ENABLED = true;

type Props = {
  detail: ContentDetail;
  artifact: ContentArtifact;
  shareToken?: string | null;
};

function readInlineFromDetail(
  detail: ContentDetail,
  artifact: ContentArtifact
): string | null {
  const raw = detail.payload?.raw_data;
  if (!raw || typeof raw !== 'object') return null;
  const source = artifact.source;
  if (!source.startsWith('raw_data.')) return null;
  const key = source.slice('raw_data.'.length);
  const value = (raw as Record<string, unknown>)[key];
  if (value == null) return null;
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

function truncateLines(
  text: string,
  maxLines: number
): { text: string; truncated: boolean } {
  const lines = text.split('\n');
  if (lines.length <= maxLines) {
    return { text, truncated: false };
  }
  return {
    text: lines.slice(0, maxLines).join('\n'),
    truncated: true
  };
}

function VirtualTextPreview({ text }: { text: string }) {
  const lines = useMemo(() => text.split('\n'), [text]);
  const [scrollTop, setScrollTop] = useState(0);
  const viewportHeight = VIRTUAL_VIEWPORT_LINES * VIRTUAL_LINE_HEIGHT_PX;
  const start = Math.max(0, Math.floor(scrollTop / VIRTUAL_LINE_HEIGHT_PX) - 4);
  const visibleCount = VIRTUAL_VIEWPORT_LINES + 8;
  const slice = lines.slice(start, start + visibleCount);
  const offsetY = start * VIRTUAL_LINE_HEIGHT_PX;
  const totalHeight = lines.length * VIRTUAL_LINE_HEIGHT_PX;

  return (
    <div
      className='h-[min(60vh,520px)] w-full overflow-y-auto rounded-md border bg-muted/20'
      onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
    >
      <div style={{ height: totalHeight, position: 'relative' }}>
        <pre
          className='absolute left-0 right-0 whitespace-pre-wrap break-all p-3 font-mono text-[11px] leading-4'
          style={{ transform: `translateY(${offsetY}px)` }}
        >
          {slice.join('\n')}
        </pre>
      </div>
    </div>
  );
}

export function ArtifactPreview({ detail, artifact, shareToken }: Props) {
  const t = useTranslations('contentFeature.detail');
  const [previewError, setPreviewError] = useState(false);
  const [textPreview, setTextPreview] = useState<string | null>(null);
  const [loadingText, setLoadingText] = useState(false);
  const [showFullText, setShowFullText] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [directImageFailed, setDirectImageFailed] = useState(false);

  const resolvedUrl = useMemo(
    () => resolveArtifactUrl(artifact.url, deviceFarmBackendBase),
    [artifact.url]
  );

  const directImageUrl = useMemo(
    () => directObjectStorageUrl(artifact.url, resolvedUrl),
    [artifact.url, resolvedUrl]
  );

  const isImage = isImageArtifact(artifact.kind, resolvedUrl, {
    label: artifact.label,
    mimeType: artifact.mime_type,
    source: artifact.source
  });
  const shouldShowImagePreview = CONTENT_IMAGE_PREVIEW_ENABLED && isImage;
  const canOpenStorageLink = Boolean(directImageUrl);
  const artifactExpired = artifact.status === 'expired';
  const needsProxyImage =
    shouldShowImagePreview &&
    (directImageFailed ||
      !directImageUrl ||
      shouldProxyArtifactFetch(artifact.url, resolvedUrl));

  const {
    data: proxyImageSrc,
    isError: proxyImageError,
    isLoading: proxyImageLoading
  } = useQuery({
    queryKey: [
      'content-artifact-image',
      detail.id,
      artifact.id,
      shareToken ?? ''
    ],
    queryFn: async () => {
      const { blob } = await contentApi.downloadArtifact(
        detail.id,
        artifact.id,
        shareToken
      );
      return URL.createObjectURL(blob);
    },
    enabled: needsProxyImage && !artifactExpired,
    staleTime: 10 * 60_000,
    gcTime: 15 * 60_000,
    refetchOnWindowFocus: false,
    retry: 1
  });

  const proxyBlobRef = useRef<string | null>(null);
  useEffect(() => {
    if (proxyImageSrc?.startsWith('blob:')) {
      proxyBlobRef.current = proxyImageSrc;
    }
    return () => {
      if (proxyBlobRef.current) {
        URL.revokeObjectURL(proxyBlobRef.current);
        proxyBlobRef.current = null;
      }
    };
  }, [proxyImageSrc]);

  useEffect(() => {
    setDirectImageFailed(false);
    setPreviewError(false);
    setShowFullText(false);
    setTextPreview(null);
  }, [artifact.id, detail.id]);

  const imageSrc = needsProxyImage
    ? (proxyImageSrc ?? null)
    : (directImageUrl ?? null);
  const imageLoadFailed =
    shouldShowImagePreview &&
    !artifactExpired &&
    (proxyImageError || (needsProxyImage && !proxyImageLoading && !imageSrc));
  const isExpired = artifactExpired || previewError || imageLoadFailed;

  useEffect(() => {
    if (isImage || isExpired) return;

    const inline = artifact.inline
      ? readInlineFromDetail(detail, artifact)
      : null;
    if (inline != null) {
      if (!showFullText && inline.length > LARGE_INLINE_BYTES) {
        setTextPreview(inline.slice(0, LARGE_INLINE_BYTES));
      } else {
        setTextPreview(inline);
      }
      return;
    }

    if (!resolvedUrl) return;

    let cancelled = false;
    setLoadingText(true);
    contentApi
      .fetchArtifactText(resolvedUrl)
      .then((text) => {
        if (cancelled) return;
        if (!showFullText && text.length > LARGE_INLINE_BYTES) {
          setTextPreview(text.slice(0, LARGE_INLINE_BYTES));
        } else {
          setTextPreview(text);
        }
      })
      .catch(() => {
        if (!cancelled) setPreviewError(true);
      })
      .finally(() => {
        if (!cancelled) setLoadingText(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    artifact.id,
    detail.id,
    isImage,
    artifactExpired,
    resolvedUrl,
    showFullText
  ]);

  const displayText = useMemo(() => {
    if (!textPreview) return null;
    if (showFullText) return textPreview;
    return truncateLines(textPreview, PREVIEW_LINE_LIMIT).text;
  }, [showFullText, textPreview]);

  const textTruncated = useMemo(() => {
    if (!textPreview) return false;
    if (!showFullText && textPreview.length >= LARGE_INLINE_BYTES) return true;
    return truncateLines(textPreview, PREVIEW_LINE_LIMIT).truncated;
  }, [showFullText, textPreview]);

  const handleDownload = async () => {
    if (directImageUrl) {
      window.open(directImageUrl, '_blank', 'noopener,noreferrer');
      return;
    }
    setDownloading(true);
    try {
      const { blob, filename } = await contentApi.downloadArtifact(
        detail.id,
        artifact.id,
        shareToken
      );
      const fallback = `content_${detail.id.slice(0, 8)}_${artifact.id.replace(/:/g, '_')}.bin`;
      triggerBlobDownload(blob, filename ?? fallback);
    } finally {
      setDownloading(false);
    }
  };

  const useVirtualizedText =
    showFullText && (textPreview?.length ?? 0) > LARGE_INLINE_BYTES;

  if (isExpired) {
    return (
      <div className='flex min-h-[200px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed bg-muted/30 p-6 text-center text-sm text-muted-foreground'>
        <AlertTriangle className='size-8 text-amber-500' />
        <p>{t('artifactExpired')}</p>
      </div>
    );
  }

  return (
    <div className='flex min-h-[240px] flex-col rounded-lg border bg-card'>
      <div className='flex items-center justify-between gap-2 border-b px-3 py-2'>
        <div className='min-w-0'>
          <p className='truncate text-sm font-medium'>{artifact.label}</p>
          <p className='truncate text-[11px] text-muted-foreground'>
            {artifact.kind}
            {artifact.size_bytes != null
              ? ` · ${(artifact.size_bytes / 1024).toFixed(1)} KB`
              : ''}
          </p>
        </div>
        <div className='flex shrink-0 items-center gap-1'>
          {canOpenStorageLink ? (
            <Button
              type='button'
              size='sm'
              variant='ghost'
              className='h-8 text-xs'
              asChild
            >
              <a
                href={directImageUrl ?? undefined}
                target='_blank'
                rel='noopener noreferrer'
              >
                {t('openStorageLink', { default: 'Mở link storage' })}
              </a>
            </Button>
          ) : null}
          <Button
            type='button'
            size='sm'
            variant='outline'
            className='h-8 gap-1'
            disabled={downloading}
            onClick={() => void handleDownload()}
          >
            {downloading ? (
              <Loader2 className='size-3.5 animate-spin' />
            ) : (
              <Download className='size-3.5' />
            )}
            {t('download')}
          </Button>
        </div>
      </div>

      <div className='min-h-0 flex-1 p-3'>
        {shouldShowImagePreview ? (
          <div className='flex max-h-[min(60vh,520px)] items-center justify-center overflow-hidden rounded-md bg-muted/40'>
            {imageSrc ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={imageSrc}
                alt={artifact.label}
                className='max-h-[min(60vh,520px)] w-full object-contain'
                onError={() => {
                  if (
                    directImageUrl &&
                    !directImageFailed &&
                    !needsProxyImage
                  ) {
                    setDirectImageFailed(true);
                  }
                }}
              />
            ) : proxyImageLoading || (directImageUrl && !directImageFailed) ? (
              <p className='flex items-center gap-2 p-4 text-sm text-muted-foreground'>
                <Loader2 className='size-4 animate-spin' />
                {t('loadingPreview')}
              </p>
            ) : null}
          </div>
        ) : loadingText ? (
          <p className='flex items-center gap-2 text-sm text-muted-foreground'>
            <Loader2 className='size-4 animate-spin' />
            {t('loadingPreview')}
          </p>
        ) : displayText ? (
          useVirtualizedText ? (
            <VirtualTextPreview text={textPreview ?? ''} />
          ) : (
            <ScrollArea className='h-[min(60vh,520px)] w-full rounded-md border bg-muted/20'>
              <pre className='whitespace-pre-wrap break-all p-3 font-mono text-[11px] leading-relaxed'>
                {displayText}
              </pre>
            </ScrollArea>
          )
        ) : (
          <p className='text-sm text-muted-foreground'>{t('noPreview')}</p>
        )}

        {textTruncated ? (
          <Button
            type='button'
            variant='link'
            className='mt-2 h-auto p-0 text-xs'
            onClick={() => setShowFullText(true)}
          >
            {t('loadFullArtifact')}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
