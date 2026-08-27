import { formatFarmApiError } from '@/lib/format-farm-api-error';

type FarmApiErrorLike = {
  response?: unknown;
  message?: string;
  code?: string;
};

function isNetworkError(err: unknown): boolean {
  const e = err as FarmApiErrorLike;
  return (
    e.code === 'ERR_NETWORK' ||
    (typeof e.message === 'string' &&
      /network error/i.test(e.message) &&
      !e.response)
  );
}

export function formatPublicAuthError(
  err: unknown,
  fallback: string,
  networkFallback: string
): string {
  if (isNetworkError(err)) {
    return networkFallback;
  }
  return formatFarmApiError(err, fallback);
}
