import assert from 'node:assert/strict';
import test from 'node:test';

import {
  analyzeStepConfiguration,
  analyzeStepConfigurationTree
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './step-configuration-status.ts';
import {
  createDefaultStep
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from '../components/scenario-steps/types.ts';

test('analyzeStepConfiguration reports missing required fields from default incomplete steps', () => {
  const cases = [
    {
      step: createDefaultStep('tap_image'),
      expected: ['imageTemplate']
    },
    {
      step: createDefaultStep('verify_screen'),
      expected: ['imageTemplate']
    },
    {
      step: createDefaultStep('input_selector'),
      expected: ['selector', 'text']
    },
    {
      step: createDefaultStep('if_variable'),
      expected: ['variableName', 'comparisonValue']
    },
    {
      step: createDefaultStep('run_scenario'),
      expected: ['scenarioReference']
    },
    {
      step: createDefaultStep('adb_shell'),
      expected: ['command']
    }
  ];

  for (const { step, expected } of cases) {
    const status = analyzeStepConfiguration(step);
    assert.equal(status.state, 'missing', step.type);
    assert.deepEqual(
      status.missingFields.map((issue) => issue.labelKey),
      expected,
      step.type
    );
  }
});

test('analyzeStepConfiguration does not warn for valid default action steps', () => {
  for (const type of ['wait', 'tap_ratio', 'swipe_ratio', 'extract']) {
    const status = analyzeStepConfiguration(createDefaultStep(type));

    assert.equal(status.state, 'complete', type);
    assert.equal(status.issues.length, 0, type);
  }
});

test('analyzeStepConfiguration treats empty containers as warnings unless they are structurally invalid', () => {
  const repeat = analyzeStepConfiguration(createDefaultStep('repeat'));
  assert.equal(repeat.state, 'warning');
  assert.deepEqual(
    repeat.warnings.map((issue) => issue.labelKey),
    ['childSteps']
  );

  const randomPick = analyzeStepConfiguration(createDefaultStep('random_pick'));
  assert.equal(randomPick.state, 'warning');
  assert.deepEqual(randomPick.warnings[0]?.values, { number: 1 });

  const invalidRandomPick = analyzeStepConfiguration({
    type: 'random_pick',
    branches: []
  });
  assert.equal(invalidRandomPick.state, 'missing');
  assert.deepEqual(
    invalidRandomPick.missingFields.map((issue) => issue.labelKey),
    ['randomBranch']
  );
});

test('analyzeStepConfiguration recognizes configured selectors, variables, and sub-scenario references', () => {
  assert.equal(
    analyzeStepConfiguration({
      ...createDefaultStep('tap_selector'),
      value: 'Continue',
      selector: { by: 'text', value: 'Continue' }
    }).state,
    'complete'
  );
  assert.equal(
    analyzeStepConfiguration({
      ...createDefaultStep('if_variable'),
      name: 'HAS_TARGET',
      equals: 'true',
      then: [{ type: 'wait', seconds: 1 }],
      else: []
    }).state,
    'complete'
  );
  assert.equal(
    analyzeStepConfiguration({
      ...createDefaultStep('run_scenario'),
      scenario_id: 'scenario-1'
    }).state,
    'complete'
  );
  assert.equal(
    analyzeStepConfiguration({
      ...createDefaultStep('verify_screen'),
      template_key: 'org/scenario/image-template.png'
    }).state,
    'complete'
  );
  assert.equal(
    analyzeStepConfiguration({
      ...createDefaultStep('verify_screen'),
      template_key: '',
      screenshot: 'data:image/jpeg;base64,legacy'
    }).state,
    'complete'
  );
});

test('analyzeStepConfigurationTree returns step-tree path keys with each status', () => {
  const tree = analyzeStepConfigurationTree([
    {
      type: 'if_variable',
      name: 'HAS_TARGET',
      equals: 'true',
      then: [createDefaultStep('tap_image')],
      else: []
    },
    createDefaultStep('wait')
  ]);

  assert.deepEqual(
    tree.map((entry) => ({
      pathKey: entry.pathKey,
      type: entry.step.type,
      state: entry.status.state
    })),
    [
      { pathKey: 'steps:0', type: 'if_variable', state: 'complete' },
      { pathKey: 'steps:0/then:0', type: 'tap_image', state: 'missing' },
      { pathKey: 'steps:1', type: 'wait', state: 'complete' }
    ]
  );
});
