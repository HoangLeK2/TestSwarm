export function sanitizeMultiFollowerSerials(
  currentFollowers: string[],
  allowedFollowers: string[],
  maxFollowers: number
) {
  const allowed = new Set(allowedFollowers);
  return currentFollowers
    .filter((serial) => allowed.has(serial))
    .slice(0, maxFollowers);
}

export function resetFollowersAfterPrimaryChange(
  previousPrimary: string | null,
  nextPrimary: string | null,
  currentFollowers: string[]
) {
  if (previousPrimary && previousPrimary !== nextPrimary) {
    return [];
  }
  return currentFollowers;
}

export function getRenderSafeFollowerSerials(
  previousPrimary: string | null,
  currentPrimary: string | null,
  currentFollowers: string[]
) {
  if (previousPrimary && previousPrimary !== currentPrimary) {
    return [];
  }
  return currentFollowers;
}

export function getActiveMultiSerials(
  primarySerial: string | null | undefined,
  followerSerials: string[]
) {
  if (!primarySerial) return [];
  return [
    primarySerial,
    ...followerSerials.filter((serial) => serial !== primarySerial)
  ];
}
