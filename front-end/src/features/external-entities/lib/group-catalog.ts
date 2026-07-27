export type GroupOpenMode = 'direct' | 'search' | 'unavailable';

export type GroupCatalogFilters = {
  search?: string;
  status?: string;
  limit?: number;
  offset?: number;
};

type GroupOpenCandidate = {
  canonical_url?: string | null;
  external_id?: string | null;
  current_attributes?: Record<string, unknown> | null;
};

type GroupSnapshotCandidate = {
  current_attributes?: Record<string, unknown> | null;
  current_metrics?: Record<string, unknown> | null;
  last_seen_at?: string | null;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value == null || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function nonEmptyString(value: unknown): boolean {
  return typeof value === 'string' && value.trim().length > 0;
}

export function buildGroupCatalogParams(filters: GroupCatalogFilters) {
  const search = filters.search?.trim();
  const status = filters.status?.trim();
  return {
    platform: 'facebook',
    entity_type: 'group',
    ...(search ? { search } : {}),
    ...(status ? { status } : {}),
    ...(filters.limit != null ? { limit: filters.limit } : {}),
    ...(filters.offset != null ? { offset: filters.offset } : {})
  };
}

export function getGroupOpenMode(entity: GroupOpenCandidate): GroupOpenMode {
  if (
    nonEmptyString(entity.canonical_url) ||
    nonEmptyString(entity.external_id)
  ) {
    return 'direct';
  }

  const locator = asRecord(entity.current_attributes?.locator);
  if (
    locator &&
    nonEmptyString(locator.search_query) &&
    asRecord(locator.selector)
  ) {
    return 'search';
  }

  return 'unavailable';
}

export function getSafeGroupUrl(
  entity: Pick<GroupOpenCandidate, 'canonical_url'>
): string | null {
  if (!nonEmptyString(entity.canonical_url)) return null;
  try {
    const url = new URL(String(entity.canonical_url));
    const safeProtocol = url.protocol === 'http:' || url.protocol === 'https:';
    const facebookHost =
      url.hostname === 'facebook.com' || url.hostname.endsWith('.facebook.com');
    const groupPath =
      url.pathname === '/groups' || url.pathname.startsWith('/groups/');
    return safeProtocol && facebookHost && groupPath ? url.toString() : null;
  } catch {
    return null;
  }
}

export function getGroupPrivacy(entity: GroupSnapshotCandidate): string | null {
  const value = entity.current_attributes?.privacy;
  return nonEmptyString(value) ? String(value).trim().toLowerCase() : null;
}

export function getGroupMemberCount(
  entity: GroupSnapshotCandidate
): number | null {
  const value = entity.current_metrics?.member_count;
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? value
    : null;
}

export function isGroupStale(
  entity: GroupSnapshotCandidate,
  now = new Date(),
  staleAfterDays = 7
): boolean {
  if (!entity.last_seen_at) return true;
  const lastSeen = new Date(entity.last_seen_at);
  if (Number.isNaN(lastSeen.getTime())) return true;
  return (
    now.getTime() - lastSeen.getTime() > staleAfterDays * 24 * 60 * 60 * 1000
  );
}
