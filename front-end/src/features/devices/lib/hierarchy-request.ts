export const HIERARCHY_REQUEST_TIMEOUT_MS = 5000;
export const HIERARCHY_FAILURE_COOLDOWN_MS = 12_000;

export function shouldBackoffHierarchyError(err: unknown): boolean {
  const responseStatus = (err as { response?: { status?: number } })?.response
    ?.status;
  if (responseStatus === 503) return true;

  const code = String((err as { code?: unknown })?.code ?? '');
  return code === 'ECONNABORTED' || code === 'ETIMEDOUT';
}
