export function boundedInt(
  value: string | number | undefined,
  fallback: number,
  min: number,
  max: number
) {
  const raw = Number(value ?? fallback);
  if (!Number.isFinite(raw)) return fallback;
  return Math.max(min, Math.min(max, Math.round(raw)));
}

export const FOLLOWER_H264_ATTACH_DWELL_MS = boundedInt(
  process.env.NEXT_PUBLIC_DEVICE_FARM_FOLLOWER_H264_ATTACH_DWELL_MS,
  750,
  0,
  5_000
);

export const FOLLOWER_PREVIEW_REFRESH_MS = boundedInt(
  process.env.NEXT_PUBLIC_DEVICE_FARM_FOLLOWER_PREVIEW_MS,
  3_000,
  1_000,
  10_000
);

export const FOLLOWER_PREVIEW_MAX_AGE_MS = Math.max(
  FOLLOWER_PREVIEW_REFRESH_MS,
  boundedInt(
    process.env.NEXT_PUBLIC_DEVICE_FARM_FOLLOWER_PREVIEW_MAX_AGE_MS,
    10_000,
    1_000,
    30_000
  )
);
