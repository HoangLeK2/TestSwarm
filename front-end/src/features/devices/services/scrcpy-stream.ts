import { farmApi } from '@/lib/farm-api';
import { createSingleFlight } from '../lib/single-flight';
import { clearH264Cache } from './ws';

const SCRCPY_STREAM_TIMEOUT_MS = 10_000;
const SCRCPY_VIEWER_HEARTBEAT_MS = (() => {
  const raw = Number(
    process.env.NEXT_PUBLIC_DEVICE_FARM_SCRCPY_VIEWER_HEARTBEAT_MS ?? 15_000
  );
  if (!Number.isFinite(raw)) return 15_000;
  return Math.max(1_000, Math.min(15_000, Math.round(raw)));
})();
const LEASED_VIEWER_PREFIXES = [
  'campaign-monitor:',
  'control-screen:',
  'device-screen:',
  'follower-preview:',
  'snapshot-preview:'
] as const;

type ScrcpyViewerHeartbeat = {
  timer: ReturnType<typeof setTimeout> | null;
  inFlight: Promise<unknown> | null;
  recoveryInFlight: Promise<void> | null;
  options: ScrcpyAttachOptions | undefined;
};

const scrcpyViewerHeartbeats = new Map<string, ScrcpyViewerHeartbeat>();

export type ScrcpyAttachOptions = {
  enableControl?: boolean;
  maxFps?: number;
  maxWidth?: number;
  bitrate?: number;
};

function scrcpyAttachPayload(viewerId?: string, options?: ScrcpyAttachOptions) {
  const payload: Record<string, unknown> = {};
  if (viewerId) payload.viewer_id = viewerId;
  if (options?.enableControl !== undefined) {
    payload.enable_control = options.enableControl;
  }
  if (options?.maxFps !== undefined) payload.max_fps = options.maxFps;
  if (options?.maxWidth !== undefined) payload.max_width = options.maxWidth;
  if (options?.bitrate !== undefined) payload.bitrate = options.bitrate;
  return payload;
}

function scrcpyAttachKey(
  serial: string,
  viewerId?: string,
  options?: ScrcpyAttachOptions
) {
  return [
    serial,
    viewerId ?? 'legacy',
    options?.enableControl ?? 'default',
    options?.maxFps ?? 'default',
    options?.maxWidth ?? 'default',
    options?.bitrate ?? 'default'
  ].join(':');
}

function scrcpyViewerHeartbeatKey(serial: string, viewerId: string): string {
  return JSON.stringify([serial, viewerId]);
}

function viewerUsesLease(viewerId?: string): viewerId is string {
  return (
    viewerId !== undefined &&
    LEASED_VIEWER_PREFIXES.some((prefix) => viewerId.startsWith(prefix))
  );
}

function scheduleScrcpyViewerHeartbeat(
  serial: string,
  viewerId: string,
  options?: ScrcpyAttachOptions
) {
  const key = scrcpyViewerHeartbeatKey(serial, viewerId);
  const existing = scrcpyViewerHeartbeats.get(key);
  if (existing) {
    existing.options = options;
    return;
  }

  const heartbeat: ScrcpyViewerHeartbeat = {
    timer: null,
    inFlight: null,
    recoveryInFlight: null,
    options
  };
  scrcpyViewerHeartbeats.set(key, heartbeat);

  const recoverViewer = async () => {
    try {
      await farmApi.post(
        `/devices/${encodeURIComponent(serial)}/scrcpy/attach`,
        scrcpyAttachPayload(viewerId, heartbeat.options),
        {
          timeout: SCRCPY_STREAM_TIMEOUT_MS,
          _skip429Retry: viewerId.startsWith('snapshot-preview:')
        }
      );
    } catch {
      return;
    }
    if (scrcpyViewerHeartbeats.has(key)) return;
    try {
      await farmApi.post(
        `/devices/${encodeURIComponent(serial)}/scrcpy/detach`,
        { viewer_id: viewerId },
        { timeout: SCRCPY_STREAM_TIMEOUT_MS }
      );
    } catch {
      // The backend lease still expires if cleanup cannot be delivered.
    }
  };

  const tick = () => {
    const current = scrcpyViewerHeartbeats.get(key);
    if (current !== heartbeat) return;
    current.timer = null;
    const operationPromise = (async () => {
      try {
        await farmApi.post(
          `/devices/${encodeURIComponent(serial)}/scrcpy/heartbeat`,
          { viewer_id: viewerId },
          { timeout: SCRCPY_STREAM_TIMEOUT_MS }
        );
      } catch (error) {
        if (
          scrcpyAttachErrorStatus(error) === 404 &&
          scrcpyViewerHeartbeats.get(key) === heartbeat
        ) {
          const recovery = recoverViewer();
          heartbeat.recoveryInFlight = recovery;
          await recovery;
        }
      } finally {
        const latest = scrcpyViewerHeartbeats.get(key);
        if (latest === heartbeat) {
          latest.inFlight = null;
          latest.timer = setTimeout(tick, SCRCPY_VIEWER_HEARTBEAT_MS);
        }
        heartbeat.recoveryInFlight = null;
      }
    })();
    current.inFlight = operationPromise;
  };

  heartbeat.timer = setTimeout(tick, SCRCPY_VIEWER_HEARTBEAT_MS);
}

function stopScrcpyViewerHeartbeat(
  serial: string,
  viewerId?: string
): Promise<void> | null {
  if (!viewerId) return null;
  const key = scrcpyViewerHeartbeatKey(serial, viewerId);
  const heartbeat = scrcpyViewerHeartbeats.get(key);
  if (!heartbeat) return null;
  scrcpyViewerHeartbeats.delete(key);
  if (heartbeat.timer) clearTimeout(heartbeat.timer);
  return heartbeat.recoveryInFlight;
}

function scrcpyAttachErrorStatus(error: unknown): number | null {
  if (!error || typeof error !== 'object' || !('response' in error))
    return null;
  const response = (error as { response?: { status?: unknown } }).response;
  return typeof response?.status === 'number' ? response.status : null;
}

export function shouldClearH264CacheBeforeScrcpyAttach(
  viewerId?: string
): boolean {
  return (
    viewerId?.startsWith('device-screen:') === true ||
    viewerId?.startsWith('control-screen:') === true
  );
}

export function scrcpyAttachErrorMessage(error: unknown): string {
  if (!error || typeof error !== 'object' || !('response' in error)) return '';
  const response = (
    error as { response?: { data?: { error?: unknown; detail?: unknown } } }
  ).response;
  const message = response?.data?.error ?? response?.data?.detail;
  return typeof message === 'string' ? message : '';
}

export function isRecoverableScrcpyAttachError(error: unknown): boolean {
  const status = scrcpyAttachErrorStatus(error);
  if (status === 404 || status === 503) return true;
  if (status !== 400) return false;

  const message = scrcpyAttachErrorMessage(error).toLowerCase();
  return (
    message.includes('device ip') ||
    message.includes('no ip') ||
    message.includes('not found') ||
    message.includes('not available') ||
    message.includes('unavailable')
  );
}

export function createScrcpyViewerId(prefix: string): string {
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}:${random}`;
}

export const attachScrcpyStream = createSingleFlight(
  async (serial: string, viewerId?: string, options?: ScrcpyAttachOptions) => {
    const pendingRecovery = stopScrcpyViewerHeartbeat(serial, viewerId);
    await pendingRecovery?.catch(() => undefined);
    const skip429Retry = viewerId?.startsWith('snapshot-preview:') === true;
    if (shouldClearH264CacheBeforeScrcpyAttach(viewerId)) {
      clearH264Cache(serial);
    }
    const { data } = await farmApi.post(
      `/devices/${encodeURIComponent(serial)}/scrcpy/attach`,
      scrcpyAttachPayload(viewerId, options),
      { timeout: SCRCPY_STREAM_TIMEOUT_MS, _skip429Retry: skip429Retry }
    );
    if (viewerUsesLease(viewerId)) {
      scheduleScrcpyViewerHeartbeat(serial, viewerId, options);
    }
    return data;
  },
  scrcpyAttachKey
);

export const detachScrcpyStream = createSingleFlight(
  async (serial: string, viewerId?: string) => {
    void stopScrcpyViewerHeartbeat(serial, viewerId);
    const { data } = await farmApi.post(
      `/devices/${encodeURIComponent(serial)}/scrcpy/detach`,
      viewerId ? { viewer_id: viewerId } : {},
      { timeout: SCRCPY_STREAM_TIMEOUT_MS }
    );
    return data;
  },
  (serial, viewerId) => `${serial}:${viewerId ?? 'legacy'}`
);
