import type { ScenarioLibraryItem } from './scenario-library-item';

export type ScenarioRoleFilter = 'all' | 'regular' | 'recovery';

function isRecoveryScenario(item: ScenarioLibraryItem): boolean {
  return (
    item.is_recovery_scenario === true || (item.recovery_usage_count ?? 0) > 0
  );
}

export function filterScenarioLibraryItems(
  items: ScenarioLibraryItem[],
  options: {
    search: string;
    showHidden: boolean;
    roleFilter: ScenarioRoleFilter;
    category?: string;
  }
): ScenarioLibraryItem[] {
  let filtered = items;

  if (!options.showHidden) {
    filtered = filtered.filter((item) => item.status !== 'archived');
  }

  if (options.roleFilter !== 'all') {
    filtered = filtered.filter((item) => {
      const isRecovery = isRecoveryScenario(item);
      return options.roleFilter === 'recovery' ? isRecovery : !isRecovery;
    });
  }

  if (options.category && options.category !== 'all') {
    filtered = filtered.filter((item) => item.category === options.category);
  }

  const query = options.search.trim().toLocaleLowerCase();
  if (!query) return filtered;

  return filtered.filter(
    (item) =>
      item.name.toLocaleLowerCase().includes(query) ||
      item.description.toLocaleLowerCase().includes(query) ||
      item.tags.some((tag) => tag.toLocaleLowerCase().includes(query))
  );
}

export { isRecoveryScenario };
