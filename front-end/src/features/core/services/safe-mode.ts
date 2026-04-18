/**
 * Safe-mode flags published by the backend at /api/server/safe-mode.
 *
 * read_only       → hide write UI (edit scenario, run tap/swipe, start session)
 * stream_hierarchy → skip the hierarchy/ui_elements polling + drop hit_test
 *
 * Fetched once on app boot via `useSafeMode()` and shared through a lightweight
 * Zustand-style subscribe so every component sees the same flags without
 * re-fetching.
 */
import { farmApi } from '@/lib/farm-api';

export type SafeMode = {
  read_only: boolean;
  stream_hierarchy: boolean;
};

const DEFAULT: SafeMode = { read_only: false, stream_hierarchy: true };

let _cache: SafeMode | null = null;
let _inflight: Promise<SafeMode> | null = null;
const _listeners = new Set<(mode: SafeMode) => void>();

function _notify(mode: SafeMode): void {
  _listeners.forEach((fn) => {
    try {
      fn(mode);
    } catch {
      /* ignore listener errors */
    }
  });
}

export async function fetchSafeMode(force = false): Promise<SafeMode> {
  if (_cache && !force) return _cache;
  if (_inflight) return _inflight;
  _inflight = (async () => {
    try {
      const { data } = await farmApi.get<SafeMode>('/server/safe-mode');
      _cache = {
        read_only: Boolean(data?.read_only),
        stream_hierarchy: data?.stream_hierarchy !== false,
      };
    } catch {
      _cache = { ...DEFAULT };
    }
    _notify(_cache);
    return _cache;
  })();
  try {
    return await _inflight;
  } finally {
    _inflight = null;
  }
}

export function getSafeModeSync(): SafeMode {
  return _cache ?? DEFAULT;
}

export function subscribeSafeMode(fn: (mode: SafeMode) => void): () => void {
  _listeners.add(fn);
  // Prime late subscribers with the current cache.
  if (_cache) fn(_cache);
  return () => {
    _listeners.delete(fn);
  };
}

export function isReadOnly(): boolean {
  return getSafeModeSync().read_only;
}

export function isHierarchyEnabled(): boolean {
  return getSafeModeSync().stream_hierarchy;
}
