'use client';

import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileCode2, Loader2 } from 'lucide-react';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { contentApi } from '@/features/content/services/api';
import {
  directObjectStorageUrl,
  shouldProxyArtifactFetch
} from '@/features/content/lib/artifact-url';
import { Z_CAMPAIGN_MONITOR_NESTED } from '@/lib/z-index';
import type { ExecutionArtifact } from '../../types';

interface Props {
  artifact: ExecutionArtifact;
  href: string;
  label: string;
}

export function ArtifactMonitorTile({ artifact, href, label }: Props) {
  const [failed, setFailed] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const needsAuthFetch = shouldProxyArtifactFetch(artifact.url, href);
  const publicUrl = directObjectStorageUrl(artifact.url, href);

  const {
    data: authImageSrc,
    isError: authFetchError,
    isLoading: authLoading
  } = useQuery({
    queryKey: ['monitor-artifact-blob', href],
    queryFn: async () => {
      const blob = await contentApi.fetchArtifactBlob(href);
      return URL.createObjectURL(blob);
    },
    enabled: needsAuthFetch && !!href,
    staleTime: 10 * 60_000,
    gcTime: 15 * 60_000,
    refetchOnWindowFocus: false,
    retry: 1
  });

  useEffect(() => {
    return () => {
      if (authImageSrc?.startsWith('blob:')) {
        URL.revokeObjectURL(authImageSrc);
      }
    };
  }, [authImageSrc]);

  const imageSrc = needsAuthFetch
    ? (authImageSrc ?? undefined)
    : (publicUrl ?? href);
  const showFailed = failed || (needsAuthFetch && authFetchError);
  const showLoading = needsAuthFetch ? authLoading && !imageSrc : !imageSrc;

  const handleOpen = () => {
    if (showFailed || !imageSrc) return;
    if (needsAuthFetch) {
      setPreviewOpen(true);
      return;
    }
    window.open(imageSrc, '_blank', 'noopener,noreferrer');
  };

  return (
    <>
      <button
        type='button'
        onClick={handleOpen}
        disabled={showFailed || !imageSrc}
        className='w-full overflow-hidden rounded-lg border bg-muted/30 text-left shadow-sm transition hover:ring-2 hover:ring-primary/30 disabled:cursor-not-allowed disabled:opacity-60'
        title={label}
      >
        <div className='aspect-video bg-muted'>
          {showFailed ? (
            <div className='flex h-full flex-col items-center justify-center gap-2 px-2 text-center text-xs text-muted-foreground'>
              <FileCode2 size={22} className='opacity-70' />
              <span className='line-clamp-2'>{artifact.artifact_type}</span>
            </div>
          ) : showLoading ? (
            <div className='flex h-full items-center justify-center text-muted-foreground'>
              <Loader2 size={18} className='animate-spin' />
            </div>
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={imageSrc}
              alt={label}
              className='h-full w-full object-cover'
              loading='lazy'
              onError={() => setFailed(true)}
            />
          )}
        </div>
      </button>

      {needsAuthFetch ? (
        <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
          <DialogContent
            zIndex={Z_CAMPAIGN_MONITOR_NESTED}
            className='max-h-[90dvh] max-w-[min(96vw,900px)] p-2 sm:p-4'
          >
            <DialogTitle className='sr-only'>{label}</DialogTitle>
            {imageSrc ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={imageSrc}
                alt={label}
                className='max-h-[min(82dvh,800px)] w-full object-contain'
              />
            ) : null}
          </DialogContent>
        </Dialog>
      ) : null}
    </>
  );
}
