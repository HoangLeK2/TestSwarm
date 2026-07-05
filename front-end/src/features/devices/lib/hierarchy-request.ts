export const HIERARCHY_REQUEST_TIMEOUT_MS = 5000;
export const HIERARCHY_FAILURE_COOLDOWN_MS = 12_000;

export type FetchHierarchyOptions = {
  /**
   * Interaction-critical callers, such as mirror tap recording, need the
   * hierarchy from the exact tap screen. They must not reuse a slower
   * auto-refresh/poll request that may have started on an older screen.
   */
  bypassInFlight?: boolean;
  /**
   * User-triggered refresh must always reach the backend. Background callers
   * still honor cooldown so a recovering uiautomator2 service is not spammed.
   */
  bypassBackoff?: boolean;
};

export function shouldReuseHierarchyInFlight(
  options?: FetchHierarchyOptions
): boolean {
  return options?.bypassInFlight !== true;
}

export function shouldRespectHierarchyBackoff(
  options?: FetchHierarchyOptions
): boolean {
  return options?.bypassBackoff !== true;
}

export function shouldBackoffHierarchyError(err: unknown): boolean {
  const responseStatus = (err as { response?: { status?: number } })?.response
    ?.status;
  if (responseStatus === 503) return true;

  const code = String((err as { code?: unknown })?.code ?? '');
  return code === 'ECONNABORTED' || code === 'ETIMEDOUT';
}
