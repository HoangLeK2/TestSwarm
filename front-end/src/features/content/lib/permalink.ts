export const AUTH_RETURN_TO_KEY = 'auth.returnTo';

export function buildContentPermalink(
  origin: string,
  locale: string,
  contentId: string,
  shareToken: string
): string {
  const base = origin.replace(/\/+$/, '');
  return `${base}/${locale}/dashboard/content/${contentId}?share=${encodeURIComponent(shareToken)}`;
}

export function saveAuthReturnTo(pathWithSearch: string): void {
  if (typeof window === 'undefined') return;
  sessionStorage.setItem(AUTH_RETURN_TO_KEY, pathWithSearch);
}

export function consumeAuthReturnTo(): string | null {
  if (typeof window === 'undefined') return null;
  const value = sessionStorage.getItem(AUTH_RETURN_TO_KEY);
  if (value) sessionStorage.removeItem(AUTH_RETURN_TO_KEY);
  return value;
}
