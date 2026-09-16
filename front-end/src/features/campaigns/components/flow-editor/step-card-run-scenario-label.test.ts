import assert from 'node:assert/strict';
import test from 'node:test';

import { resolveRunScenarioCardRef } from './run-scenario-card-label.ts';

test('run_scenario card displays org scenario name instead of UUID', () => {
  const scenarioId = '34091ee6-80ec-4db4-94a1-449f2b3be2d3';
  const scenarioName = 'Đăng nhập Facebook copy';
  const step = {
    type: 'run_scenario',
    scenario_id: scenarioId,
    variables: {}
  };

  assert.equal(
    resolveRunScenarioCardRef(step, [{ id: scenarioId, name: scenarioName }]),
    scenarioName
  );
});

test('run_scenario manual name still wins over matching org scenario name', () => {
  assert.equal(
    resolveRunScenarioCardRef(
      {
        type: 'run_scenario',
        scenario_id: 'child-1',
        scenario_name: 'Tên nhập tay'
      },
      [{ id: 'child-1', name: 'Tên trong workspace' }]
    ),
    'Tên nhập tay'
  );
});

test('run_scenario card falls back to UUID while scenario catalog is loading', () => {
  const scenarioId = '34091ee6-80ec-4db4-94a1-449f2b3be2d3';
  assert.equal(
    resolveRunScenarioCardRef({ type: 'run_scenario', scenario_id: scenarioId }),
    scenarioId
  );
});
