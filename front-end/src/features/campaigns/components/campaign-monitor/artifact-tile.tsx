'use client';

import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileCode2, Loader2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { contentApi } from '@/features/content/services/api';
import {
  directObjectStorageUrl,
  shouldProxyArtifactFetch
} from '@/features/content/lib/artifact-url';
import { cn } from '@/lib/utils';
import type { ExecutionArtifact } from '../../types';

interface Props {
  artifact: ExecutionArtifact;
  href: string;
  label: string;
  deviceLabel: string;
  subtitle: string;
  stepNumber?: number | null;
  isFail?: boolean;
  timeLabel?: string;
  hideDeviceLabel?: boolean;
  compact?: boolean;
}

function isBlobLike(value: unknown): value is Blob {
  return (
    typeof Blob !== 'undefined' &&
    value instanceof Blob &&
    value.size >= 0
  );
}

function blobToObjectUrl(value: unknown): string | undefined {
  if (!isBlobLike(value)) return undefined;
  try {
    return URL.createObjectURL(value);
  } catch {
    return undefined;
  }
}

function useMonitorArtifactImageSrc(artifact: ExecutionArtifact, href: string) {
  const [directFailed, setDirectFailed] = useState(false);
  const [renderFailed, setRenderFailed] = useState(false);

  useEffect(() => {
    setDirectFailed(false);
    setRenderFailed(false);
  }, [href, artifact.url]);

  const directUrl = useMemo(
    () => directObjectStorageUrl(artifact.url, href),
    [artifact.url, href]
  );

  const needsProxy =
    directFailed ||
    !directUrl ||
    shouldProxyArtifactFetch(artifact.url, href);

  const {
    data: blob,
    isError: proxyError,
    isLoading: proxyLoading
  } = useQuery({
    queryKey: ['monitor-artifact-blob-v2', href],
    queryFn: async () => {
      const data = await contentApi.fetchArtifactBlob(href);
      if (!isBlobLike(data)) {
        throw new TypeError('Artifact response is not a Blob');
      }
      return data;
    },
    enabled: needsProxy && !!href,
    staleTime: 10 * 60_000,
    gcTime: 15 * 60_000,
    refetchOnWindowFocus: false,
    retry: 2
  });

  const blobUrl = useMemo(() => blobToObjectUrl(blob), [blob]);

  useEffect(() => {
    return () => {
      if (blobUrl?.startsWith('blob:')) {
        URL.revokeObjectURL(blobUrl);
      }
    };
  }, [blobUrl]);

  const imageSrc = needsProxy ? blobUrl : (directUrl ?? undefined);
  const showLoading = needsProxy ? !blobUrl && !proxyError : !directUrl;
  const showFailed =
    renderFailed ||
    (needsProxy && proxyError) ||
    (needsProxy && !proxyLoading && Boolean(blob) && !blobUrl);

  const onImageError = () => {
    if (directUrl && !directFailed && !needsProxy) {
      setDirectFailed(true);
      return;
    }
    setRenderFailed(true);
  };

  return { imageSrc, showLoading, showFailed, onImageError };
}

export function ArtifactMonitorTile({
  artifact,
  href,
  label,
  deviceLabel,
  subtitle,
  stepNumber,
  isFail = false,
  timeLabel,
  hideDeviceLabel = false,
  compact = false
}: Props) {
  const t = useTranslations('campaignsFeature.list');
  const { imageSrc, showLoading, showFailed, onImageError } =
    useMonitorArtifactImageSrc(artifact, href);
  const previewMaxClass = compact
    ? 'max-h-[min(28vh,240px)]'
    : 'max-h-[min(40vh,320px)]';

  return (
    <Card className='gap-0 overflow-hidden py-0 shadow-none'>
      <CardHeader className='gap-1 border-b px-3 py-2'>
        <div className='flex flex-wrap items-center gap-1.5'>
          {stepNumber != null ? (
            <Badge
              variant='secondary'
              className='h-5 px-1.5 text-[10px] font-bold tabular-nums'
            >
              B{stepNumber}
            </Badge>
          ) : null}
          {isFail ? (
            <Badge
              variant='destructive'
              className='h-5 px-1.5 text-[10px] font-bold'
            >
              !
            </Badge>
          ) : null}
          {!hideDeviceLabel ? (
            <span className='truncate text-xs font-semibold'>{deviceLabel}</span>
          ) : null}
        </div>
        <p className='text-[11px] leading-snug text-muted-foreground'>{subtitle}</p>
        {timeLabel ? (
          <p className='text-[10px] text-muted-foreground'>{timeLabel}</p>
        ) : null}
      </CardHeader>

      <CardContent className='p-2'>
        <div
          className={cn(
            'flex items-center justify-center overflow-hidden rounded-md bg-muted/40',
            previewMaxClass
          )}
        >
          {showFailed ? (
            <div className='flex flex-col items-center justify-center gap-2 px-3 py-6 text-center text-xs text-muted-foreground'>
              <FileCode2 size={22} className='opacity-70' />
              <span>{t('monitorArtifactPreviewUnavailable')}</span>
              <span className='text-[10px] opacity-80'>{label}</span>
            </div>
          ) : showLoading ? (
            <div className='flex items-center justify-center py-10 text-muted-foreground'>
              <Loader2 size={20} className='animate-spin' />
            </div>
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={imageSrc}
              alt={label}
              className={cn('w-full object-contain', previewMaxClass)}
              loading='eager'
              decoding='async'
              onError={onImageError}
            />
          )}
        </div>
      </CardContent>
    </Card>
  );
}
