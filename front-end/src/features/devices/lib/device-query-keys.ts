export const DEVICES_LIST_KEY = ['devices'] as const;
export const FLEET_STATS_KEY = ['devices', 'fleet-stats'] as const;

export function devicesListQueryKey(orgId: string | null | undefined) {
  return [...DEVICES_LIST_KEY, orgId ?? 'none'] as const;
}

export function fleetStatsQueryKey(orgId: string | null | undefined) {
  return [...FLEET_STATS_KEY, orgId ?? 'none'] as const;
}
