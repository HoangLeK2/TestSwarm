export type WebCodecsSupport = 'unknown' | 'supported' | 'unsupported';

export type DeviceTilePreviewMode = {
  useH264: boolean;
  useSnapshot: boolean;
};

type MediaPreviewDevice = {
  state?: string | null;
  media_adapter_connected?: boolean;
  media_stream_active?: boolean;
  media_stream_connected?: boolean;
};

const TERMINAL_OFFLINE_STATES = new Set(['DISCONNECTED', 'DEAD']);

export function isGridH264Enabled(rawValue: string | undefined): boolean {
  return (rawValue ?? '1').trim() !== '0';
}

export function isGridWebRtcPreviewEnabled(
  rawValue: string | undefined
): boolean {
  return (rawValue ?? '1').trim() !== '0';
}

export function hasMediaPlanePreview(device: MediaPreviewDevice): boolean {
  return Boolean(
    device.media_adapter_connected ||
      device.media_stream_active ||
      device.media_stream_connected
  );
}

export function isDevicePreviewStreamEligible(
  device: MediaPreviewDevice,
  controlPlaneActive: boolean
): boolean {
  if (hasMediaPlanePreview(device)) return true;
  const state = String(device.state || '')
    .replace('DeviceState.', '')
    .trim()
    .toUpperCase();
  return controlPlaneActive && !TERMINAL_OFFLINE_STATES.has(state);
}

export function selectDeviceTilePreviewMode({
  h264Enabled,
  webCodecsSupport,
  h264Stalled
}: {
  h264Enabled: boolean;
  webCodecsSupport: WebCodecsSupport;
  h264Stalled: boolean;
}): DeviceTilePreviewMode {
  const useH264 = h264Enabled && webCodecsSupport === 'supported';
  return {
    useH264,
    useSnapshot:
      !h264Enabled ||
      webCodecsSupport === 'unsupported' ||
      (useH264 && h264Stalled)
  };
}

/** Two misses, not one: a single dropped poll is normal on a busy grid. */
export const SNAPSHOT_FAILURES_BEFORE_STALE = 2;

/**
 * A frame already painted stops being evidence once its source stops moving.
 * Keeping it on screen is how a dead phone reads as live to an operator.
 */
export function isPreviewFrameStale({
  streamStatus,
  consecutiveSnapshotFailures
}: {
  streamStatus?: string | null;
  consecutiveSnapshotFailures: number;
}): boolean {
  if (streamStatus === 'stale') return true;
  return consecutiveSnapshotFailures >= SNAPSHOT_FAILURES_BEFORE_STALE;
}

export function nextSnapshotRetryDelayMs({
  consecutiveFailureCount,
  refreshMs
}: {
  consecutiveFailureCount: number;
  refreshMs: number;
}): number {
  const exponent = Math.max(0, Math.floor(consecutiveFailureCount) - 1);
  return Math.min(15_000, refreshMs * 2 ** exponent);
}
