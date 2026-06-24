const DEFAULT_BACKEND_BASE = (
  process.env.NEXT_PUBLIC_PRODUCT_API_URL || 'http://localhost:8081'
).replace(/\/+$/, '');

const OBJECT_STORAGE_PUBLIC_BASE = (
  process.env.NEXT_PUBLIC_OBJECT_STORAGE_PUBLIC_BASE_URL ||
  process.env.NEXT_PUBLIC_R2_PUBLIC_BASE_URL ||
  ''
).replace(/\/+$/, '');

/** Rewrite legacy dev MinIO URLs (localhost:9000) to the public R2/CDN base. */
export function rewriteLegacyObjectStorageUrl(
  url: string | null | undefined
): string | null {
  if (!url) return null;
  const value = url.trim();
  if (!value || !OBJECT_STORAGE_PUBLIC_BASE) return value || null;
  const match = value.match(
    /^https?:\/\/(?:localhost|127\.0\.0\.1):\d+(?:\/device-farm)?\/(content-screenshots\/[^?#]+)/i
  );
  if (!match) return value;
  return `${OBJECT_STORAGE_PUBLIC_BASE}/${match[1]}`;
}

/** Resolve artifact preview/download URLs against the farm API origin. */
export function resolveArtifactUrl(
  url: string | null | undefined,
  backendBase: string = DEFAULT_BACKEND_BASE
): string | null {
  if (!url) return null;
  const value = url.trim();
  if (!value) return null;
  if (value.startsWith('http://') || value.startsWith('https://')) {
    return rewriteLegacyObjectStorageUrl(value);
  }
  const base = backendBase.replace(/\/+$/, '');
  if (value.startsWith('/')) {
    return `${base}${value}`;
  }
  return `${base}/${value}`;
}

export function isAbsoluteHttpUrl(url: string | null | undefined): boolean {
  if (!url) return false;
  return /^https?:\/\//i.test(url.trim());
}

/** Farm API routes that require JWT — never use as <img src> directly. */
function isFarmApiArtifactRoute(url: string): boolean {
  const value = url.trim();
  return (
    value.startsWith('/api/artifacts/') ||
    value.startsWith('/api/content/') ||
    /\/api\/artifacts\/[^/]+\/content/.test(value) ||
    /\/api\/content\/[^/]+\/artifacts\//.test(value)
  );
}

/** Execution artifact proxy stored in DB (private object, needs farm stream). */
function isExecutionArtifactProxyPath(url: string): boolean {
  return /^\/artifacts\/[0-9a-f-]{36}\/content$/i.test(url.trim());
}

/**
 * Use MinIO/R2 public (or presigned) URLs directly in the browser.
 * Proxy via farm API only for private execution artifacts, farm API paths, and local disk paths.
 */
export function shouldProxyArtifactFetch(
  rawUrl: string | null | undefined,
  resolvedUrl: string | null
): boolean {
  const raw = (rawUrl ?? '').trim();
  if (!raw) return true;

  if (isFarmApiArtifactRoute(raw) || isExecutionArtifactProxyPath(raw)) {
    return true;
  }

  // Static capture files are mounted at app root (/captures), not under /api.
  if (raw.startsWith('/captures/') || raw.startsWith('captures/')) {
    return false;
  }

  const legacyScreenshot =
    raw.startsWith('screenshots/') || raw.startsWith('/screenshots');

  if (legacyScreenshot) return true;

  // Absolute MinIO/R2/public CDN — browser loads directly (no farm download hop).
  if (isAbsoluteHttpUrl(raw)) {
    return isFarmApiArtifactRoute(raw);
  }

  // Relative path resolved to farm origin (local disk fallback).
  if (resolvedUrl && isAbsoluteHttpUrl(resolvedUrl)) {
    return isFarmApiArtifactRoute(resolvedUrl);
  }

  return Boolean(resolvedUrl);
}

/** Public object-storage URL for <img src> / open in tab; null when farm proxy is required. */
export function directObjectStorageUrl(
  rawUrl: string | null | undefined,
  resolvedUrl: string | null
): string | null {
  const raw = (rawUrl ?? '').trim();
  if (isAbsoluteHttpUrl(raw) && !shouldProxyArtifactFetch(raw, raw)) {
    return raw;
  }
  if (!resolvedUrl || shouldProxyArtifactFetch(rawUrl, resolvedUrl)) {
    return null;
  }
  return resolvedUrl;
}

export type ImageArtifactHints = {
  label?: string | null;
  mimeType?: string | null;
  source?: string | null;
};

export function isImageArtifact(
  kind: string,
  url: string | null,
  hints?: ImageArtifactHints
): boolean {
  if (kind === 'image') return true;
  const mime = hints?.mimeType?.trim();
  if (mime?.startsWith('image/')) return true;
  const label = (hints?.label ?? '').toLowerCase();
  const source = (hints?.source ?? '').toLowerCase();
  if (/\bscreenshot\b/.test(label) || /\bscreenshot\b/.test(source))
    return true;
  if (!url) return false;
  return /\.(png|jpe?g|webp|gif)(\?|$)/i.test(url);
}
