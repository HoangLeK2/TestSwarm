'use client';

import { ImageIcon, Loader2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { deviceFarmBackendBase } from '@/lib/farm-api';
import {
  directObjectStorageUrl,
  isImageArtifact,
  resolveArtifactUrl,
  shouldProxyArtifactFetch
} from '@/features/content/lib/artifact-url';
import type { ExecutionArtifact } from '../../types';
import { useLatestExecutionArtifacts } from '../../hooks/use-campaigns';
import { MonitorSectionHeader } from './monitor-section-header';
import { ArtifactMonitorTile } from './artifact-tile';

interface Props {
  campaignId: string;
  pollAggressive?: boolean;
}

function resolvedArtifactHref(artifact: ExecutionArtifact): string | null {
  const raw = String(artifact.url ?? '').trim();
  if (!raw) return null;

  const resolved = resolveArtifactUrl(raw, deviceFarmBackendBase);
  const direct = directObjectStorageUrl(raw, resolved);
  if (direct) return direct;

  if (shouldProxyArtifactFetch(raw, resolved)) {
    if (raw.startsWith('/artifacts/')) {
      return resolveArtifactUrl(`/api${raw}`, deviceFarmBackendBase);
    }
    if (artifact.artifact_type === 'content_screenshot') {
      const contentId = String(artifact.metadata?.content_id ?? '').trim();
      if (contentId) {
        return resolveArtifactUrl(
          `/api/content/${encodeURIComponent(contentId)}/artifacts/screenshot/download`,
          deviceFarmBackendBase
        );
      }
    }
  }

  return resolved;
}

function artifactIsImage(
  artifact: ExecutionArtifact,
  href: string | null
): boolean {
  const kind = String(artifact.metadata?.content_type || '');
  if (kind.startsWith('image/')) return true;
  if (artifact.artifact_type.includes('screenshot')) return true;
  return isImageArtifact(kind, href);
}

export function ArtifactPanel({ campaignId, pollAggressive = true }: Props) {
  const t = useTranslations('campaignsFeature.list');
  const { data, isLoading } = useLatestExecutionArtifacts(
    campaignId,
    true,
    pollAggressive
  );
  const artifacts = data?.artifacts ?? [];
  const withUrl = artifacts.filter((artifact) => {
    const href = resolvedArtifactHref(artifact);
    return Boolean(href) && artifactIsImage(artifact, href);
  });

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
          {withUrl.slice(0, 24).map((artifact, idx) => {
            const href = resolvedArtifactHref(artifact);
            if (!href) return null;
            const label = `${artifact.artifact_type} · ${artifact.device_serial || t('monitorArtifactDeviceUnknown')}`;
            return (
              <ArtifactMonitorTile
                key={`${artifact.execution_id}-${artifact.artifact_type}-${idx}`}
                artifact={artifact}
                href={href}
                label={label}
              />
            );
          })}
        </div>
      ) : null}
    </section>
  );
}
