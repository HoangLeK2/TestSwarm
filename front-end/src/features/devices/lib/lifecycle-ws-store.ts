'use client';

import { useSyncExternalStore } from 'react';

let connected = false;
const listeners = new Set<() => void>();

export function setLifecycleWsConnected(next: boolean) {
  if (connected === next) return;
  connected = next;
  listeners.forEach((listener) => listener());
}

export function getLifecycleWsConnected() {
  return connected;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useLifecycleWsConnected() {
  return useSyncExternalStore(subscribe, getLifecycleWsConnected, () => false);
}

/** Fallback poll when lifecycle WS is live (transport/last_seen still need sync). */
export const LIFECYCLE_WS_LIVE_POLL_MS = 120_000;
export const LIFECYCLE_WS_OFFLINE_POLL_MS = 30_000;
