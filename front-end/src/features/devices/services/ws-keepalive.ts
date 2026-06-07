export const DEVICE_FARM_WS_FOCUS_STALE_MS = 45_000;
export const DEVICE_FARM_WS_CLIENT_PING_INTERVAL_MS = 20_000;
export const DEVICE_FARM_WS_RECONNECT_BASE_MS = 2_000;
export const DEVICE_FARM_WS_RECONNECT_MAX_MS = 30_000;

export function shouldReconnectStaleSocketOnFocus(
  lastMessageAt: number,
  now = Date.now(),
  staleMs = DEVICE_FARM_WS_FOCUS_STALE_MS
): boolean {
  return lastMessageAt > 0 && now - lastMessageAt > staleMs;
}

export function nextReconnectDelayMs(
  failedAttempts: number,
  baseMs = DEVICE_FARM_WS_RECONNECT_BASE_MS,
  maxMs = DEVICE_FARM_WS_RECONNECT_MAX_MS
): number {
  const attempt = Math.max(0, Math.floor(failedAttempts));
  return Math.min(maxMs, baseMs * 2 ** attempt);
}
