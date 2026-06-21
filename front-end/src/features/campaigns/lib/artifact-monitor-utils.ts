import {
  directObjectStorageUrl,
  isImageArtifact,
  resolveArtifactUrl,
  shouldProxyArtifactFetch
} from '@/features/content/lib/artifact-url';
import type { ExecutionArtifact } from '../types';

const ARTIFACT_BACKEND_BASE = (
  process.env.NEXT_PUBLIC_PRODUCT_API_URL || 'http://localhost:8081'
).replace(/\/+$/, '');

export function resolvedArtifactHref(
  artifact: ExecutionArtifact
): string | null {
  const raw = String(artifact.url ?? '').trim();
  if (!raw) return null;

  const resolved = resolveArtifactUrl(raw, ARTIFACT_BACKEND_BASE);
  const direct = directObjectStorageUrl(raw, resolved);
  if (direct) return direct;

  if (shouldProxyArtifactFetch(raw, resolved)) {
    if (raw.startsWith('/artifacts/')) {
      return resolveArtifactUrl(`/api${raw}`, ARTIFACT_BACKEND_BASE);
    }
    if (artifact.artifact_type === 'content_screenshot') {
      const contentId = String(artifact.metadata?.content_id ?? '').trim();
      if (contentId) {
        return resolveArtifactUrl(
          `/api/content/${encodeURIComponent(contentId)}/artifacts/screenshot/download`,
          ARTIFACT_BACKEND_BASE
        );
      }
    }
  }

  return resolved;
}

export function artifactIsImage(
  artifact: ExecutionArtifact,
  href: string | null
): boolean {
  const type = artifact.artifact_type.toLowerCase();
  if (type.includes('hierarchy') || type.endsWith('.selector')) return false;

  const kind = String(artifact.metadata?.content_type || '');
  if (kind.startsWith('application/xml')) return false;
  if (kind.startsWith('image/')) return true;
  if (type.includes('screenshot')) return true;
  return isImageArtifact(kind, href);
}

export function countMonitorImageArtifacts(
  artifacts: ExecutionArtifact[]
): number {
  return artifacts.filter((artifact) => {
    const href = resolvedArtifactHref(artifact);
    return Boolean(href) && artifactIsImage(artifact, href);
  }).length;
}

export function buildExecutionShotCounts(
  executionIds: string[],
  artifactsByExecutionId: Map<string, ExecutionArtifact[] | undefined>
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const id of executionIds) {
    const artifacts = artifactsByExecutionId.get(id);
    counts.set(id, artifacts ? countMonitorImageArtifacts(artifacts) : 0);
  }
  return counts;
}
