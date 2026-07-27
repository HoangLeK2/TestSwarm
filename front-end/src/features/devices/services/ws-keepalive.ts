export const DEVICE_FARM_WS_FOCUS_STALE_MS = 45_000;
export const DEVICE_FARM_WS_CLIENT_PING_INTERVAL_MS = 20_000;
export const DEVICE_FARM_WS_RECONNECT_BASE_MS = 500;
export const DEVICE_FARM_WS_RECONNECT_MAX_MS = 5_000;
export const DEVICE_FARM_IDR_HARD_MIN_INTERVAL_MS = 300;

export function shouldSendIdrRequest(
  lastSentAt: number,
  now: number,
  requestedMinIntervalMs: number
): boolean {
  const requested = Number.isFinite(requestedMinIntervalMs)
    ? Math.max(0, requestedMinIntervalMs)
    : 0;
  const minInterval = Math.max(DEVICE_FARM_IDR_HARD_MIN_INTERVAL_MS, requested);
  return lastSentAt <= 0 || now - lastSentAt >= minInterval;
}

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

export function isCurrentDeviceFarmWsEvent<T>(
  currentSocket: T | null | undefined,
  eventSocket: T | null | undefined
): boolean {
  return currentSocket === eventSocket;
}
