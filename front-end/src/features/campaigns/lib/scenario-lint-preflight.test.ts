import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import type { FlowStep } from '../components/scenario-steps/types.ts';
import {
  scenarioLintIssueSeverity,
  scenarioLintPreflightForInlineRun,
  scenarioLintPreflightForSteps,
  scenarioLintSummary,
  stepTreePathKeyForInlineRunKey
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './scenario-lint-preflight.ts';

const steps = (value: FlowStep[]) => value;

test('classifies structural target issues as critical preflight issues', () => {
  const result = scenarioLintPreflightForSteps(
    steps([{ type: 'connection_request', action: 'request' }])
  );

  assert.equal(result.hasCritical, true);
  assert.equal(result.criticalIssues[0]?.kind, 'missing_verified_target');
  assert.equal(scenarioLintIssueSeverity(result.criticalIssues[0]), 'critical');
  assert.deepEqual(result.warningIssues, []);
});

test('classifies unknown variable references as warning-only preflight issues', () => {
  const result = scenarioLintPreflightForSteps(
    steps([{ type: 'input_text', text: '${MISSING_NAME}' }])
  );

  assert.equal(result.hasCritical, false);
  assert.equal(result.warningIssues[0]?.kind, 'unknown_reference');
  assert.equal(scenarioLintIssueSeverity(result.warningIssues[0]), 'warning');
});

test('inline preflight keeps only issues for the selected nested step', () => {
  const result = scenarioLintPreflightForInlineRun(
    steps([
      {
        type: 'if_variable',
        name: 'HAS_TARGET',
        equals: 'true',
        then: [{ type: 'input_text', text: '${ONLY_THEN_MISSING}' }],
        else: [{ type: 'input_text', text: '${ONLY_ELSE_MISSING}' }]
      }
    ]),
    '0/then:0',
    { type: 'input_text', text: '${ONLY_THEN_MISSING}' },
    ['HAS_TARGET']
  );

  assert.deepEqual(
    result.issues.map((issue) => issue.variable),
    ['ONLY_THEN_MISSING']
  );
  assert.equal(result.issues[0]?.pathKey, 'steps:0/then:0');
});

test('inline preflight also checks the selected step as an isolated preview run', () => {
  const result = scenarioLintPreflightForInlineRun(
    steps([
      { type: 'set_variable', name: 'PREVIOUS_VALUE', value: 'ready' },
      { type: 'input_text', text: '${PREVIOUS_VALUE}' }
    ]),
    '1',
    { type: 'input_text', text: '${PREVIOUS_VALUE}' }
  );

  assert.deepEqual(
    result.issues.map((issue) => [issue.kind, issue.variable, issue.pathKey]),
    [['unknown_reference', 'PREVIOUS_VALUE', 'steps:1']]
  );
});

test('inline preflight decodes branch run keys with the runtime steps suffix', () => {
  assert.equal(
    stepTreePathKeyForInlineRunKey('0/branches.1.steps:0'),
    'steps:0/branches.1:0'
  );

  const result = scenarioLintPreflightForInlineRun(
    steps([
      {
        type: 'random_pick',
        branches: [
          { steps: [{ type: 'input_text', text: '${BRANCH_ZERO}' }] },
          { steps: [{ type: 'input_text', text: '${BRANCH_ONE}' }] }
        ]
      }
    ]),
    '0/branches.1.steps:0',
    { type: 'input_text', text: '${BRANCH_ONE}' }
  );

  assert.deepEqual(
    result.issues.map((issue) => issue.variable),
    ['BRANCH_ONE']
  );
});

test('summary limits visible issues and appends the provided more label', () => {
  const result = scenarioLintPreflightForSteps(
    steps([
      { type: 'input_text', text: '${ONE}' },
      { type: 'input_text', text: '${TWO}' },
      { type: 'input_text', text: '${THREE}' }
    ])
  );

  assert.equal(
    scenarioLintSummary(result.issues, {
      limit: 2,
      formatIssue: (issue) => issue.variable,
      moreLabel: (count) => `and ${count} more`
    }),
    'ONE; TWO; and 1 more'
  );
});

test('control record save paths run scenario lint before persisting', () => {
  const source = readFileSync(
    new URL(
      '../../devices/components/control-record-view.tsx',
      import.meta.url
    ),
    'utf8'
  );

  assert.match(source, /lintCurrentScenarioBeforePersist/);
  assert.match(source, /handlePrimarySave/);
  assert.match(source, /handleSaveAsNewCampaignScenario/);
  assert.match(source, /handleSaveToCampaignScenario/);
  assert.match(
    source,
    /scenarioLintPreflightForSteps\(\s*latestSteps,\s*scenarioLintInitialVariables\s*\)/
  );
});

test('control record preview-stream paths run scenario lint before dispatch', () => {
  const source = readFileSync(
    new URL(
      '../../devices/components/control-record-view.tsx',
      import.meta.url
    ),
    'utf8'
  );
  const leafRun = source.slice(
    source.indexOf('const handleFlowRunLeaf'),
    source.indexOf('const flowEditorValue')
  );
  const inlineRun = source.slice(
    source.indexOf('const handleRunStep'),
    source.indexOf('const runDeviceOpStep')
  );
  const deviceOpRun = source.slice(
    source.indexOf('const runDeviceOpStep'),
    source.indexOf('const handleSelectorPickedFromHierarchy')
  );

  assert.ok(leafRun.includes('preparePreviewStepPayload(step)'));
  assert.ok(leafRun.includes('scenarioLintPreflightForSteps'));
  assert.ok(leafRun.includes('previewScenarioStream'));
  assert.ok(
    leafRun.indexOf('scenarioLintPreflightForSteps') <
      leafRun.indexOf('previewScenarioStream')
  );

  assert.ok(inlineRun.includes('prepareInlinePreviewStep'));
  assert.ok(inlineRun.includes('scenarioLintPreflightForInlineRun'));
  assert.ok(inlineRun.includes('previewScenarioStream'));
  assert.ok(
    inlineRun.indexOf('scenarioLintPreflightForInlineRun') <
      inlineRun.indexOf('previewScenarioStream')
  );

  assert.ok(deviceOpRun.includes('preparePreviewStepPayload(step)'));
  assert.ok(deviceOpRun.includes('scenarioLintPreflightForSteps'));
  assert.ok(deviceOpRun.includes('previewScenarioStream'));
  assert.ok(
    deviceOpRun.indexOf('scenarioLintPreflightForSteps') <
      deviceOpRun.indexOf('previewScenarioStream')
  );
});

test('run campaign dialog runs scenario lint before capability preflight and dispatch', () => {
  const source = readFileSync(
    new URL('../components/run-campaign-dialog.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /runScenarioLintPreflight/);
  assert.match(source, /scenarioLintPreflightForSteps/);
  assert.match(
    source,
    /if \(!\(await runScenarioLintPreflight\(\)\)\) return;\s*const serials/
  );
  assert.match(source, /runCapabilityPreflight\(serials\)/);
});

test('scenario lint preflight messages exist for campaign and device control surfaces', () => {
  const locales = ['en', 'vi'] as const;
  const requiredIssueKeys = [
    'unknown_reference',
    'future_reference',
    'maybe_unavailable',
    'missing_verified_target',
    'candidate_lease_without_entity',
    'source_var_without_scan',
    'verified_target_without_profile',
    'comment_flow_missing_step'
  ];

  for (const locale of locales) {
    const messages = JSON.parse(
      readFileSync(
        new URL(`../../../../messages/${locale}.json`, import.meta.url),
        'utf8'
      )
    );
    for (const node of [
      messages.campaignsFeature?.scenarioLintPreflight,
      messages.devicesControlRecord?.scenarioLintPreflight
    ]) {
      assert.ok(node?.confirmTitle, `${locale} missing confirmTitle`);
      assert.ok(node?.saveContext, `${locale} missing saveContext`);
      assert.ok(node?.summaryMore, `${locale} missing summaryMore`);
      for (const key of requiredIssueKeys) {
        assert.ok(node?.issues?.[key], `${locale} missing issue ${key}`);
      }
    }
  }
});
