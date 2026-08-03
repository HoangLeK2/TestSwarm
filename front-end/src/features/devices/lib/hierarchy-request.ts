export const HIERARCHY_REQUEST_TIMEOUT_MS = 5000;
export const HIERARCHY_FAILURE_COOLDOWN_MS = 12_000;

export type HierarchyFetchPriority = 'background' | 'visible';

export type FetchHierarchyOptions = {
  /**
   * Foreground/control requests get the backend visible lane. Background
   * refresh/crawl requests must not consume that lane.
   */
  priority?: HierarchyFetchPriority;
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

export function resolveHierarchyFetchPriority(
  options?: FetchHierarchyOptions
): HierarchyFetchPriority {
  return options?.priority === 'visible' ? 'visible' : 'background';
}

export function buildHierarchyRequestKey(
  serial: string,
  refresh: boolean,
  options?: FetchHierarchyOptions
): string {
  return [
    serial,
    refresh ? 'refresh' : 'cached',
    resolveHierarchyFetchPriority(options)
  ].join(':');
}

export function buildHierarchyBackoffKey(
  serial: string,
  options?: FetchHierarchyOptions
): string {
  return [serial, resolveHierarchyFetchPriority(options)].join(':');
}

export function buildHierarchyUrl(
  serial: string,
  refresh: boolean,
  options?: FetchHierarchyOptions
): string {
  const params = new URLSearchParams();
  if (refresh) params.set('refresh', '1');
  if (resolveHierarchyFetchPriority(options) === 'visible') {
    params.set('priority', 'visible');
  }
  const query = params.toString();
  return `/devices/${encodeURIComponent(serial)}/hierarchy${query ? `?${query}` : ''}`;
}

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
