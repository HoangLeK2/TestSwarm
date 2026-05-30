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

export function isImageArtifact(kind: string, url: string | null): boolean {
  if (kind === 'image') return true;
  if (!url) return false;
  return /\.(png|jpe?g|webp|gif)(\?|$)/i.test(url);
}
