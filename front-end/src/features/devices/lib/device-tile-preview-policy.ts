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
