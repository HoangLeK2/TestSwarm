export const H264_INPUT_REFRESH_MIN_INTERVAL_MS = 3000;
export const H264_INPUT_REFRESH_WAIT_MS = 350;

export function shouldRequestH264RefreshAfterInput(options: {
  isActive: boolean;
  h264DecodeAllowed: boolean;
  h264Only: boolean;
  hasFrame: boolean;
  frameAdvancedSinceInput?: boolean;
  now: number;
  lastRequestAt: number;
  minIntervalMs?: number;
}): boolean {
  if (!options.isActive || !options.h264DecodeAllowed) return false;
  if (options.frameAdvancedSinceInput) return false;
  if (options.hasFrame && !options.h264Only) return false;

  const minIntervalMs =
    options.minIntervalMs ?? H264_INPUT_REFRESH_MIN_INTERVAL_MS;
  return options.now - options.lastRequestAt >= minIntervalMs;
}
