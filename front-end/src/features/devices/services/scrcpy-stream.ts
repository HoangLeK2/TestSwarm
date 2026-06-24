import { farmApi } from '@/lib/farm-api';
import { createSingleFlight } from '../lib/single-flight';

const SCRCPY_STREAM_TIMEOUT_MS = 10_000;

function scrcpyAttachErrorStatus(error: unknown): number | null {
  if (!error || typeof error !== 'object' || !('response' in error))
    return null;
  const response = (error as { response?: { status?: unknown } }).response;
  return typeof response?.status === 'number' ? response.status : null;
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
  async (serial: string, viewerId?: string) => {
    const { data } = await farmApi.post(
      `/devices/${encodeURIComponent(serial)}/scrcpy/attach`,
      viewerId ? { viewer_id: viewerId } : {},
      { timeout: SCRCPY_STREAM_TIMEOUT_MS }
    );
    return data;
  },
  (serial, viewerId) => `${serial}:${viewerId ?? 'legacy'}`
);

export const detachScrcpyStream = createSingleFlight(
  async (serial: string, viewerId?: string) => {
    const { data } = await farmApi.post(
      `/devices/${encodeURIComponent(serial)}/scrcpy/detach`,
      viewerId ? { viewer_id: viewerId } : {},
      { timeout: SCRCPY_STREAM_TIMEOUT_MS }
    );
    return data;
  },
  (serial, viewerId) => `${serial}:${viewerId ?? 'legacy'}`
);
