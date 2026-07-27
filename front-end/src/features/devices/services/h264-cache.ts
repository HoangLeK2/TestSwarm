// Keyframes older than this are considered stale. Replaying a stale IDR while
// live P-frames reference a newer one (arrived while tab hidden) drifts the
// decoder into a black state. Skip replay when stale — server-side forced IDR
// fills the gap within ~100ms.
export const H264_CACHED_KEY_STALE_MS = 5_000;

export function shouldReplayCachedKeyFrameAge(ageMs: number): boolean {
  return Number.isFinite(ageMs) && ageMs <= H264_CACHED_KEY_STALE_MS;
}

export function shouldInvalidateCachedH264KeyForConfig(
  previousConfig: ArrayBuffer | undefined,
  nextConfig: ArrayBuffer
): boolean {
  if (!previousConfig) return true;
  if (previousConfig.byteLength !== nextConfig.byteLength) return true;

  const prev = new Uint8Array(previousConfig);
  const next = new Uint8Array(nextConfig);
  const prevFlagsOffset = h264ConfigFlagsOffset(prev);
  const nextFlagsOffset = h264ConfigFlagsOffset(next);
  if (prevFlagsOffset === null || nextFlagsOffset === null) return true;
  if (prevFlagsOffset !== nextFlagsOffset) return true;
  if ((next[nextFlagsOffset] & 0x01) !== 0) return true;

  for (let i = 0; i < prev.length; i += 1) {
    if (i === prevFlagsOffset) continue;
    if (prev[i] !== next[i]) return true;
  }
  return false;
}

function h264ConfigFlagsOffset(frame: Uint8Array): number | null {
  if (frame.length < 2 || frame[0] !== 0x10) return null;
  const offset = 2 + frame[1] + 4;
  return offset < frame.length ? offset : null;
}
