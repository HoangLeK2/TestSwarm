export const DEVICE_FARM_WS_FOCUS_STALE_MS = 45_000;
export const DEVICE_FARM_WS_CLIENT_PING_INTERVAL_MS = 20_000;

export function shouldReconnectStaleSocketOnFocus(
  lastMessageAt: number,
  now = Date.now(),
  staleMs = DEVICE_FARM_WS_FOCUS_STALE_MS
): boolean {
  return lastMessageAt > 0 && now - lastMessageAt > staleMs;
}
