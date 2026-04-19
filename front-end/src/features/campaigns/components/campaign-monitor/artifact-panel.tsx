'use client';

import { ImageIcon, Loader2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { useLatestExecutionArtifacts } from '../../hooks/use-campaigns';

interface Props {
  campaignId: string;
}

export function ArtifactPanel({ campaignId }: Props) {
  const t = useTranslations('campaignsFeature.list');
  const { data, isLoading } = useLatestExecutionArtifacts(campaignId, true);
  const artifacts = data?.artifacts ?? [];

  return (
    <div className='border-t bg-blue-500/[0.02] p-3'>
      <div className='mb-2 flex items-center gap-2'>
        <ImageIcon size={14} className='text-blue-600 dark:text-blue-400' />
        <p className='text-xs font-semibold'>{t('monitorArtifactTitle')}</p>
        <Badge variant={artifacts.length > 0 ? 'default' : 'secondary'} className='ml-auto'>
          {artifacts.length}
        </Badge>
      </div>

      {isLoading ? (
        <div className='flex items-center gap-2 py-2 text-[11px] text-muted-foreground'>
          <Loader2 size={12} className='animate-spin' />
          {t('monitorArtifactLoading')}
        </div>
      ) : null}

      {!isLoading && artifacts.length === 0 ? (
        <p className='py-2 text-[11px] text-muted-foreground'>{t('monitorArtifactEmpty')}</p>
      ) : null}

      <div className='grid max-h-64 grid-cols-2 gap-2 overflow-y-auto pr-1 md:grid-cols-3'>
        {artifacts
          .filter((a) => !!a.url)
          .slice(0, 24)
          .map((artifact, idx) => (
            <a
              key={`${artifact.execution_id}-${artifact.artifact_type}-${idx}`}
              href={artifact.url || '#'}
              target='_blank'
              rel='noreferrer'
              className='group overflow-hidden rounded-md border bg-background'
              title={`${artifact.artifact_type} — ${artifact.device_serial || t('monitorArtifactDeviceUnknown')}`}
            >
              <div className='aspect-video bg-muted'>
                {artifact.url?.match(/\.(jpg|jpeg|png|webp)$/i) ? (
                  <img src={artifact.url} alt={artifact.artifact_type} className='h-full w-full object-cover' />
                ) : (
                  <div className='flex h-full items-center justify-center text-[10px] text-muted-foreground'>
                    {artifact.artifact_type}
                  </div>
                )}
              </div>
              <div className='px-2 py-1 text-[10px]'>
                <p className='truncate font-medium'>{artifact.artifact_type}</p>
                <p className='truncate text-muted-foreground'>
                  {artifact.device_serial || t('monitorArtifactDeviceUnknownSlug')}
                </p>
              </div>
            </a>
          ))}
      </div>
    </div>
  );
}
