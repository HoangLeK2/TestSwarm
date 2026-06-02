'use client';

import { useEffect, useState } from 'react';
import { FileCode2 } from 'lucide-react';
import { tokenStorage } from '@/lib/token-storage';
import type { ExecutionArtifact } from '../../types';

interface Props {
  artifact: ExecutionArtifact;
  href: string;
  showImage: boolean;
  label: string;
}

export function ArtifactMonitorTile({
  artifact,
  href,
  showImage,
  label
}: Props) {
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);

  useEffect(() => {
    setImageSrc(null);
    setImageError(false);
    if (!showImage || !href) return undefined;

    let cancelled = false;
    let objectUrl: string | null = null;
    const token = tokenStorage.getAuthToken();
    fetch(href, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined
    })
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setImageSrc(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setImageError(true);
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [href, showImage]);

  return (
    <a
      href={href}
      target='_blank'
      rel='noreferrer'
      className='overflow-hidden rounded-lg border bg-muted/30 shadow-sm transition hover:ring-2 hover:ring-primary/30'
      title={label}
    >
      <div className='aspect-video bg-muted'>
        {showImage && imageSrc && !imageError ? (
          <img
            src={imageSrc}
            alt={artifact.artifact_type}
            className='h-full w-full object-cover'
          />
        ) : (
          <div className='flex h-full flex-col items-center justify-center gap-2 px-2 text-center text-xs text-muted-foreground'>
            <FileCode2 size={22} className='opacity-70' />
            <span className='line-clamp-2'>{artifact.artifact_type}</span>
          </div>
        )}
      </div>
    </a>
  );
}
