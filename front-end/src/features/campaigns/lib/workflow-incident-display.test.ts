import assert from 'node:assert/strict';
import test from 'node:test';
import {
  detectActiveRecoveryFromEvents,
  resolveRecoveryScenarioName
} from './workflow-incident-display.ts';

test('resolveRecoveryScenarioName prefers human name over uuid id', () => {
  const name = resolveRecoveryScenarioName(
    {
      event_type: 'incident.recovery.started',
      recovery_scenario_id: '11111111-1111-4111-8111-111111111111',
      recovery_scenario_name: 'Đóng popup profile'
    },
    new Map()
  );
  assert.equal(name, 'Đóng popup profile');
});

test('resolveRecoveryScenarioName maps id through org scenario names', () => {
  const name = resolveRecoveryScenarioName(
    {
      event_type: 'incident.recovery.started',
      recovery_scenario_id: 'recovery-scenario'
    },
    new Map([['recovery-scenario', 'Đóng popup profile']])
  );
  assert.equal(name, 'Đóng popup profile');
});

test('detectActiveRecoveryFromEvents tracks latest recovery lifecycle', () => {
  const names = new Map([['recovery-scenario', 'Đóng popup profile']]);
  const started = detectActiveRecoveryFromEvents(
    [
      {
        event_id: '1',
        event_type: 'incident.recovery.started',
        execution_id: 'exec-1',
        payload: {
          recovery_scenario_id: 'recovery-scenario'
        }
      } as any
    ],
    names
  );
  assert.equal(started.active, true);
  assert.equal(started.scenarioName, 'Đóng popup profile');

  const completed = detectActiveRecoveryFromEvents(
    [
      {
        event_id: '1',
        event_type: 'incident.recovery.started',
        execution_id: 'exec-1',
        payload: { recovery_scenario_id: 'recovery-scenario' }
      } as any,
      {
        event_id: '2',
        event_type: 'incident.recovery.completed',
        execution_id: 'exec-1',
        payload: {}
      } as any
    ],
    names
  );
  assert.equal(completed.active, false);
});
