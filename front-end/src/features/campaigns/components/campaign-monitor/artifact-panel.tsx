'use client';

import { ImageIcon, Loader2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useLatestExecutionArtifacts } from '../../hooks/use-campaigns';
import { MonitorSectionHeader } from './monitor-section-header';

interface Props {
  campaignId: string;
}

export function ArtifactPanel({ campaignId }: Props) {
  const t = useTranslations('campaignsFeature.list');
  const { data, isLoading } = useLatestExecutionArtifacts(campaignId, true);
  const artifacts = data?.artifacts ?? [];
  const withUrl = artifacts.filter((a) => !!a.url);

  return (
    <section className='px-6 py-5'>
      <MonitorSectionHeader
        icon={<ImageIcon size={20} />}
        title={t('monitorArtifactTitle')}
        hint={t('monitorArtifactDescription')}
        count={withUrl.length}
        countVariant={withUrl.length > 0 ? 'default' : 'secondary'}
      />

      {isLoading ? (
        <p className='mt-4 flex items-center gap-2 text-sm text-muted-foreground'>
          <Loader2 size={16} className='animate-spin' />
          {t('monitorArtifactLoading')}
        </p>
      ) : null}

      {!isLoading && withUrl.length === 0 ? (
        <p className='mt-4 text-sm text-muted-foreground'>
          {t('monitorArtifactEmpty')}
        </p>
      ) : null}

      {!isLoading && withUrl.length > 0 ? (
        <div className='mt-4 grid max-h-[min(50vh,420px)] grid-cols-2 gap-3 overflow-y-auto sm:grid-cols-3 lg:grid-cols-4'>
          {withUrl.slice(0, 24).map((artifact, idx) => (
            <a
              key={`${artifact.execution_id}-${artifact.artifact_type}-${idx}`}
              href={artifact.url || '#'}
              target='_blank'
              rel='noreferrer'
              className='overflow-hidden rounded-lg border bg-muted/30 shadow-sm transition hover:ring-2 hover:ring-primary/30'
              title={`${artifact.artifact_type} · ${artifact.device_serial || t('monitorArtifactDeviceUnknown')}`}
            >
              <div className='aspect-video bg-muted'>
                {artifact.url?.match(/\.(jpg|jpeg|png|webp)$/i) ? (
                  <img
                    src={artifact.url}
                    alt={artifact.artifact_type}
                    className='h-full w-full object-cover'
                  />
                ) : (
                  <div className='flex h-full items-center justify-center px-2 text-center text-xs text-muted-foreground'>
                    {artifact.artifact_type}
                  </div>
                )}
              </div>
            </a>
          ))}
        </div>
      ) : null}
    </section>
  );
}
