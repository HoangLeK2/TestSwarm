export type WebCodecsSupport = 'unknown' | 'supported' | 'unsupported';

export type DeviceTilePreviewMode = {
  useH264: boolean;
  useSnapshot: boolean;
};

export function isGridH264Enabled(rawValue: string | undefined): boolean {
  return (rawValue ?? '1').trim() !== '0';
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
