import assert from 'node:assert/strict';
import test from 'node:test';

import {
  filterScenarioLibraryItems,
  type ScenarioRoleFilter
} from './filter-scenario-library-items';
import type { ScenarioLibraryItem } from './scenario-library-item';

function item(
  overrides: Partial<ScenarioLibraryItem> &
    Pick<ScenarioLibraryItem, 'id' | 'name'>
): ScenarioLibraryItem {
  return {
    description: '',
    kind: 'sequence',
    status: 'active',
    scenario_version: 1,
    tags: [],
    updated_at: '2026-08-28T00:00:00Z',
    is_runnable: true,
    source: 'org',
    is_system_template: false,
    ...overrides
  };
}

function filter(
  items: ScenarioLibraryItem[],
  search: string,
  roleFilter: ScenarioRoleFilter = 'all',
  category = 'all'
) {
  return filterScenarioLibraryItems(items, {
    search,
    showHidden: false,
    roleFilter,
    category
  });
}

test('searches organization scenarios and system templates by visible fields', () => {
  const organizationScenario = item({
    id: 'org',
    name: 'Crawl bài viết',
    description: 'Tìm bài trong nhóm',
    tags: ['facebook']
  });
  const systemTemplate = item({
    id: 'template',
    name: 'Khám phá nguồn từ Facebook',
    source: 'template',
    is_system_template: true,
    tags: ['discovery']
  });

  assert.deepEqual(filter([organizationScenario], '  CRAWL  '), [
    organizationScenario
  ]);
  assert.deepEqual(filter([systemTemplate], 'discovery'), [systemTemplate]);
});

test('keeps library status and role filters while searching', () => {
  const archived = item({
    id: 'archived',
    name: 'Facebook',
    status: 'archived'
  });
  const recovery = item({
    id: 'recovery',
    name: 'Facebook recovery',
    is_recovery_scenario: true
  });
  const regular = item({ id: 'regular', name: 'Facebook regular' });

  assert.deepEqual(
    filter([archived, recovery, regular], 'facebook', 'regular'),
    [regular]
  );
});

test('filters system templates by category', () => {
  const facebook = item({
    id: 'facebook',
    name: 'Facebook template',
    source: 'template',
    is_system_template: true,
    category: 'facebook'
  });
  const utility = item({
    id: 'utility',
    name: 'Utility template',
    source: 'template',
    is_system_template: true,
    category: 'utility'
  });

  assert.deepEqual(filter([facebook, utility], '', 'all', 'facebook'), [
    facebook
  ]);
});
