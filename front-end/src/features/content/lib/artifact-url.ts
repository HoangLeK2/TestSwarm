const DEFAULT_BACKEND_BASE = (
  process.env.NEXT_PUBLIC_PRODUCT_API_URL || 'http://localhost:8081'
).replace(/\/+$/, '');

/** Resolve artifact preview/download URLs against the farm API origin. */
export function resolveArtifactUrl(
  url: string | null | undefined,
  backendBase: string = DEFAULT_BACKEND_BASE
): string | null {
  if (!url) return null;
  const value = url.trim();
  if (!value) return null;
  if (value.startsWith('http://') || value.startsWith('https://')) {
    return value;
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

/**
 * Use MinIO/R2 (or any absolute object URL) directly in the browser.
 * Proxy via farm API only for local paths and execution artifact routes.
 */
export function shouldProxyArtifactFetch(
  rawUrl: string | null | undefined,
  resolvedUrl: string | null
): boolean {
  const raw = (rawUrl ?? '').trim();
  if (!raw) return true;

  const farmRelative =
    raw.startsWith('/artifacts') ||
    raw.includes('/artifacts/') ||
    raw.startsWith('screenshots/') ||
    raw.startsWith('/screenshots') ||
    raw.startsWith('captures/') ||
    raw.startsWith('/captures');

  if (farmRelative) return true;

  if (isAbsoluteHttpUrl(raw)) {
    return false;
  }

  // Relative path resolved to farm origin (local disk fallback).
  if (resolvedUrl && isAbsoluteHttpUrl(resolvedUrl)) {
    return true;
  }

  return Boolean(resolvedUrl);
}

/** Public URL for opening in a new tab (R2/MinIO); null when only farm proxy works. */
export function directObjectStorageUrl(
  rawUrl: string | null | undefined,
  resolvedUrl: string | null
): string | null {
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
  if (/\bscreenshot\b/.test(label) || /\bscreenshot\b/.test(source)) return true;
  if (/\belement\b/.test(label) || /\belement\b/.test(source)) return true;
  if (!url) return false;
  return /\.(png|jpe?g|webp|gif)(\?|$)/i.test(url);
}
