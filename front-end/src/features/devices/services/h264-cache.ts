// Keyframes older than this are considered stale. Replaying a stale IDR while
// live P-frames reference a newer one (arrived while tab hidden) drifts the
// decoder into a black state. Skip replay when stale — server-side forced IDR
// fills the gap within ~100ms.
export const H264_CACHED_KEY_STALE_MS = 5_000;

export function shouldReplayCachedKeyFrameAge(ageMs: number): boolean {
  return Number.isFinite(ageMs) && ageMs <= H264_CACHED_KEY_STALE_MS;
}
