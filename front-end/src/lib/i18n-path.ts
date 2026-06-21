import { routing } from '@/i18n/routing';

export function normalizeInternalAppPath(
  value: string | null | undefined,
  fallback: string
): string {
  const raw = String(value ?? '').trim();
  if (!raw || !raw.startsWith('/') || raw.startsWith('//')) return fallback;

  const locales = routing.locales.map((locale) => `/${locale}`);
  for (const prefix of locales) {
    if (raw === prefix) return '/';
    if (raw.startsWith(`${prefix}/`)) {
      return raw.slice(prefix.length) || '/';
    }
  }

  return raw;
}
