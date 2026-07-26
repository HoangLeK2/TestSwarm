type CatalogSource = {
  platform: string;
  entity_type: string;
};

const ALLOCATABLE_SOURCE_STATUSES = new Set([
  'candidate',
  'active',
  'available'
]);

export function isAllocatableSourceStatus(status: string): boolean {
  return ALLOCATABLE_SOURCE_STATUSES.has(status.trim().toLowerCase());
}

export type SourcePoolOption = {
  key: string;
  platform: string;
  entityType: string;
  count: number;
};

export function listSourcePoolOptions(
  sources: CatalogSource[]
): SourcePoolOption[] {
  const counts = new Map<string, SourcePoolOption>();
  for (const source of sources) {
    const platform = source.platform.trim().toLowerCase();
    const entityType = source.entity_type.trim().toLowerCase();
    const key = `${platform}::${entityType}`;
    const current = counts.get(key);
    counts.set(key, {
      key,
      platform,
      entityType,
      count: (current?.count ?? 0) + 1
    });
  }
  return Array.from(counts.values()).sort((left, right) =>
    left.key.localeCompare(right.key)
  );
}

export function buildSourcePoolInput(key: string, search: string) {
  const [platform = '', entityType = ''] = key.split('::', 2);
  const trimmedSearch = search.trim();
  return {
    platform,
    entity_type: entityType,
    ...(trimmedSearch ? { search: trimmedSearch } : {})
  };
}
