export type TabVisibilityState = 'hidden' | 'visible' | 'prerender';

export function shouldRunTabNetworkActivity(
  visibilityState: TabVisibilityState | undefined
): boolean {
  return visibilityState === undefined || visibilityState === 'visible';
}

export function isCurrentTabNetworkActive(): boolean {
  if (typeof document === 'undefined') return true;
  return shouldRunTabNetworkActivity(document.visibilityState);
}
