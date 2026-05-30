/**
 * Runtime status from /api/server/status (DF-T-01-007).
 */
import { farmApi } from '@/lib/farm-api';

export type ServerStatus = {
  safe_mode: boolean;
  db_connected: boolean;
  version: string;
  started_at: number;
};

const DEFAULT: ServerStatus = {
  safe_mode: false,
  db_connected: true,
  version: '1.0.0',
  started_at: Date.now() / 1000
};

let _cache: ServerStatus | null = null;
let _inflight: Promise<ServerStatus> | null = null;
const _listeners = new Set<(status: ServerStatus) => void>();
let _pollTimer: ReturnType<typeof setInterval> | null = null;

function _notify(status: ServerStatus): void {
  _listeners.forEach((fn) => {
    try {
      fn(status);
    } catch {
      /* ignore */
    }
  });
}

export async function fetchServerStatus(force = false): Promise<ServerStatus> {
  if (_cache && !force) return _cache;
  if (_inflight) return _inflight;
  _inflight = (async () => {
    try {
      const { data } = await farmApi.get<ServerStatus>('/server/status');
      _cache = {
        safe_mode: Boolean(data?.safe_mode),
        db_connected: data?.db_connected !== false,
        version: String(data?.version ?? DEFAULT.version),
        started_at: Number(data?.started_at ?? DEFAULT.started_at)
      };
    } catch {
      _cache = { ...DEFAULT, db_connected: false, safe_mode: true };
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

export function getServerStatusSync(): ServerStatus {
  return _cache ?? DEFAULT;
}

export function subscribeServerStatus(
  fn: (status: ServerStatus) => void
): () => void {
  _listeners.add(fn);
  if (_cache) fn(_cache);
  return () => {
    _listeners.delete(fn);
  };
}

export function startServerStatusPolling(intervalMs = 30_000): () => void {
  if (typeof window === 'undefined') return () => undefined;
  fetchServerStatus().catch(() => undefined);
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(() => {
    fetchServerStatus(true).catch(() => undefined);
  }, intervalMs);
  return () => {
    if (_pollTimer) {
      clearInterval(_pollTimer);
      _pollTimer = null;
    }
  };
}
