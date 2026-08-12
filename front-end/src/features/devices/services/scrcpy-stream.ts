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
const pendingScrcpyAttachControllers = new Map<string, Set<AbortController>>();

export type ScrcpyAttachOptions = {
  enableControl?: boolean;
  maxFps?: number;
  maxWidth?: number;
  bitrate?: number;
  profile?: 'visible' | 'focused' | 'degraded';
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
  if (options?.profile !== undefined) payload.profile = options.profile;
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
    options?.bitrate ?? 'default',
    options?.profile ?? 'default'
  ].join(':');
}

function scrcpyViewerHeartbeatKey(serial: string, viewerId: string): string {
  return JSON.stringify([serial, viewerId]);
}

function abortPendingScrcpyAttach(serial: string, viewerId?: string): void {
  if (!viewerId) return;
  const key = scrcpyViewerHeartbeatKey(serial, viewerId);
  const controllers = pendingScrcpyAttachControllers.get(key);
  if (!controllers) return;
  pendingScrcpyAttachControllers.delete(key);
  controllers.forEach((controller) => controller.abort());
}

export function cancelPendingScrcpyAttach(
  serial: string,
  viewerId?: string
): void {
  abortPendingScrcpyAttach(serial, viewerId);
}

async function postScrcpyAttach(
  serial: string,
  viewerId: string | undefined,
  options: ScrcpyAttachOptions | undefined,
  skip429Retry: boolean
) {
  const controller =
    viewerId && typeof AbortController !== 'undefined'
      ? new AbortController()
      : null;
  const key = viewerId ? scrcpyViewerHeartbeatKey(serial, viewerId) : null;
  if (controller && key) {
    const controllers =
      pendingScrcpyAttachControllers.get(key) ?? new Set<AbortController>();
    controllers.add(controller);
    pendingScrcpyAttachControllers.set(key, controllers);
  }
  try {
    return await farmApi.post(
      `/devices/${encodeURIComponent(serial)}/scrcpy/attach`,
      scrcpyAttachPayload(viewerId, options),
      {
        timeout: SCRCPY_STREAM_TIMEOUT_MS,
        _skip429Retry: skip429Retry,
        ...(controller ? { signal: controller.signal } : {})
      }
    );
  } finally {
    if (controller && key) {
      const controllers = pendingScrcpyAttachControllers.get(key);
      controllers?.delete(controller);
      if (controllers?.size === 0) {
        pendingScrcpyAttachControllers.delete(key);
      }
    }
  }
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
      await postScrcpyAttach(
        serial,
        viewerId,
        heartbeat.options,
        viewerId.startsWith('snapshot-preview:')
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
  if (status === 404 || status === 425 || status === 503) return true;
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

export function isScrcpyAttachCancellation(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false;
  const candidate = error as { code?: unknown; name?: unknown };
  return (
    candidate.code === 'ERR_CANCELED' || candidate.name === 'CanceledError'
  );
}

export function createScrcpyViewerId(prefix: string): string {
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}:${random}`;
}

function isPendingScrcpyAttachResponse(data: unknown): boolean {
  if (!data || typeof data !== 'object' || !('status' in data)) return false;
  return (
    String((data as { status?: unknown }).status ?? '').toLowerCase() ===
    'pending'
  );
}

function pendingScrcpyAttachError(): Error {
  return Object.assign(new Error('scrcpy stream is not ready'), {
    response: {
      status: 425,
      data: { detail: 'scrcpy stream is not ready' }
    }
  });
}

export const attachScrcpyStream = createSingleFlight(
  async (serial: string, viewerId?: string, options?: ScrcpyAttachOptions) => {
    const pendingRecovery = stopScrcpyViewerHeartbeat(serial, viewerId);
    await pendingRecovery?.catch(() => undefined);
    const skip429Retry = viewerId?.startsWith('snapshot-preview:') === true;
    if (shouldClearH264CacheBeforeScrcpyAttach(viewerId)) {
      clearH264Cache(serial);
    }
    const { data } = await postScrcpyAttach(
      serial,
      viewerId,
      options,
      skip429Retry
    );
    if (isPendingScrcpyAttachResponse(data)) {
      throw pendingScrcpyAttachError();
    }
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

/**
 * Deliver viewer cleanup while the document is unloading.
 *
 * Axios' default XHR request can be aborted by pagehide/navigation. The fetch
 * adapter with keepalive preserves the same auth/org interceptors while letting
 * the small detach request finish after the page starts unloading.
 */
export async function detachScrcpyStreamOnPageHide(
  serial: string,
  viewerId?: string
) {
  abortPendingScrcpyAttach(serial, viewerId);
  void stopScrcpyViewerHeartbeat(serial, viewerId);
  const { data } = await farmApi.post(
    `/devices/${encodeURIComponent(serial)}/scrcpy/detach`,
    viewerId ? { viewer_id: viewerId } : {},
    {
      timeout: SCRCPY_STREAM_TIMEOUT_MS,
      adapter: 'fetch',
      fetchOptions: { keepalive: true }
    }
  );
  return data;
}
