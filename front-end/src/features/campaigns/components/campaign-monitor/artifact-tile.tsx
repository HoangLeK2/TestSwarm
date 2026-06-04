'use client';

import { FileCode2 } from 'lucide-react';
import type { ExecutionArtifact } from '../../types';

interface Props {
  artifact: ExecutionArtifact;
  href: string;
  label: string;
}

export function ArtifactMonitorTile({ artifact, href, label }: Props) {
  return (
    <a
      href={href}
      target='_blank'
      rel='noreferrer'
      className='overflow-hidden rounded-lg border bg-muted/30 shadow-sm transition hover:ring-2 hover:ring-primary/30'
      title={label}
    >
      <div className='aspect-video bg-muted'>
        <div className='flex h-full flex-col items-center justify-center gap-2 px-2 text-center text-xs text-muted-foreground'>
          <FileCode2 size={22} className='opacity-70' />
          <span className='line-clamp-2'>{artifact.artifact_type}</span>
        </div>
      </div>
    </a>
  );
}
