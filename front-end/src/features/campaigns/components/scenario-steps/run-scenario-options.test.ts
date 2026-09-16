import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import {
  buildRunScenarioOptions,
  findSelectedRunScenario,
  runScenarioPatchFor
} from './run-scenario-options.ts';

const CAMPAIGN = [{ id: 'camp-1', name: 'Warm up' }];
const LIBRARY = [
  { id: 'org-sc-1', name: 'Kết bạn' },
  { id: 'org-sc-2', name: 'Đọc hồ sơ' }
];
const TEMPLATES = [
  { id: 'tpl-1', name: 'Đăng nhập Facebook', category: 'facebook' }
];

test('workspace library scenarios are offered, between campaign and templates', () => {
  const options = buildRunScenarioOptions({
    campaignScenarios: CAMPAIGN,
    libraryScenarios: LIBRARY,
    templates: TEMPLATES
  });

  assert.deepEqual(
    options.map((o) => [o.source, o.id]),
    [
      ['campaign', 'camp-1'],
      ['library', 'org-sc-1'],
      ['library', 'org-sc-2'],
      ['template', 'tpl-1']
    ]
  );
});

test('library and campaign picks write scenario_id; templates write scenario_name', () => {
  const [campaign, library, , template] = buildRunScenarioOptions({
    campaignScenarios: CAMPAIGN,
    libraryScenarios: LIBRARY,
    templates: TEMPLATES
  });

  // The registry resolves these by id — a name here would not resolve.
  assert.deepEqual(runScenarioPatchFor(campaign), {
    scenario_id: 'camp-1',
    scenario_name: undefined
  });
  assert.deepEqual(runScenarioPatchFor(library), {
    scenario_id: 'org-sc-1',
    scenario_name: undefined
  });
  assert.deepEqual(runScenarioPatchFor(template), {
    scenario_name: 'Đăng nhập Facebook',
    scenario_id: undefined
  });
});

test('a template categorised "campaign" is still addressed by name', () => {
  // `source` used to carry the template's category, so this template would
  // have been written as a scenario_id no registry contains.
  const [option] = buildRunScenarioOptions({
    templates: [{ id: 'tpl-x', name: 'Mẫu', category: 'campaign' }]
  });

  assert.equal(option.source, 'template');
  assert.equal(option.category, 'campaign');
  assert.deepEqual(runScenarioPatchFor(option), {
    scenario_name: 'Mẫu',
    scenario_id: undefined
  });
});

test('selection matches by id before name when both could hit', () => {
  const options = buildRunScenarioOptions({
    libraryScenarios: [{ id: 'org-sc-1', name: 'Kết bạn' }],
    templates: [{ id: 'tpl-1', name: 'Kết bạn', category: 'facebook' }]
  });

  assert.equal(
    findSelectedRunScenario(options, { scenarioId: 'org-sc-1' })?.source,
    'library'
  );
  assert.equal(
    findSelectedRunScenario(options, { scenarioName: 'Kết bạn' })?.source,
    'library'
  );
  assert.equal(
    findSelectedRunScenario(options, { scenarioId: 'tpl-1' })?.source,
    'template'
  );
});

test('nothing selected when the step has no ref', () => {
  const options = buildRunScenarioOptions({ libraryScenarios: LIBRARY });
  assert.equal(findSelectedRunScenario(options, {}), undefined);
  assert.equal(
    findSelectedRunScenario(options, { scenarioId: 'gone' }),
    undefined
  );
});
