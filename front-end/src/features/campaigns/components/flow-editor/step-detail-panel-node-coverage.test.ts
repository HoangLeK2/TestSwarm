import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

import {
  getInsertMenuForUi
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './constants.ts';
import {
  createDefaultStep
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from '../scenario-steps/types.ts';

const require = createRequire(import.meta.url);
const enMessages = require('../../../../../messages/en.json');
const viMessages = require('../../../../../messages/vi.json');

/**
 * The runtime schema, published by the backend as a file.
 *
 * Not a regex over scenario_schema.py: catalog metadata is overlaid at import
 * time, so only the applied result tells you what the editor receives. Not a
 * Python subprocess either — that made this test require a built device_farm
 * venv. device_farm/tests/test_scenario_schema_snapshot.py keeps the file
 * current and fails when it drifts.
 */
function readBackendScenarioSchema() {
  return JSON.parse(
    readFileSync(
      new URL('../../../../../generate/scenario-schema.json', import.meta.url),
      'utf8'
    )
  );
}

test('tap_xml_match has a dedicated step detail editor', () => {
  const source = readFileSync(
    new URL('./step-detail-panel.tsx', import.meta.url),
    'utf8'
  );
  const typesSource = readFileSync(
    new URL('../scenario-steps/types.ts', import.meta.url),
    'utf8'
  );

  assert.match(source, /step\.type === 'tap_xml_match'/);
  assert.match(source, /tapXmlMatch\.hint/);
  assert.match(source, /tapXmlMatch\.attributeLabel/);
  assert.match(typesSource, /\| 'tap_xml_match'/);
});

test('step detail panel renders node capability metadata', () => {
  const source = readFileSync(
    new URL('./step-detail-panel.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /nodeCapabilities\?\.\[step\.type\]/);
  assert.match(source, /evaluateNodeCapabilityStatus/);
  assert.match(source, /recorder_evidence/);
  assert.match(source, /inspector_hints/);
});

test('step cards and detail panel render configuration status metadata', () => {
  const stepCardSource = readFileSync(
    new URL('./step-card.tsx', import.meta.url),
    'utf8'
  );
  const detailSource = readFileSync(
    new URL('./step-detail-panel.tsx', import.meta.url),
    'utf8'
  );

  assert.match(stepCardSource, /analyzeStepConfiguration\(step\)/);
  assert.match(stepCardSource, /configurationStatus\.state !== 'complete'/);
  assert.match(detailSource, /StepConfigurationSummary/);
  assert.match(detailSource, /analyzeStepConfiguration\(step\)/);
  assert.match(
    detailSource,
    /campaignsFeature\.stepEditor\.configurationStatus/
  );
});

test('schema-driven nodes render through SchemaFields, not a hand-written branch', () => {
  const source = readFileSync(
    new URL('./step-detail-panel.tsx', import.meta.url),
    'utf8'
  );

  // The panel must actually consult the backend schema...
  assert.match(source, /schemaFieldsFor\(/);
  assert.match(source, /<SchemaFields/);

  // ...and every migrated node must gate its old branch on it, or both forms
  // render at once and the user edits the same field in two places.
  const migrated = [
    ...source.matchAll(
      /const SCHEMA_DRIVEN_STEP_TYPES = new Set\(\[([^\]]*)\]/g
    )
  ].flatMap((m) => [...m[1].matchAll(/'([^']+)'/g)].map((v) => v[1]));
  assert.ok(migrated.length > 0, 'no node types are marked schema-driven');

  for (const type of migrated) {
    assert.match(
      source,
      new RegExp(`step\\.type === '${type}' && !schemaDrivenFields`),
      `${type} is schema-driven but its hand-written branch is not gated`
    );
  }
});

test('loop is split between its hand-written editor and the schema, with no overlap', () => {
  // loop is partially migrated: LoopConfigFields keeps count/while (mode toggle
  // + ConditionBuilder), the schema supplies the safety valves that had no
  // editor. A field declared on both sides would render twice and let the user
  // edit the same value in two places.
  const schema = readBackendScenarioSchema();
  const schemaFields = Object.keys(schema.steps_schema.loop.fields ?? {});
  const editorSource = readFileSync(
    new URL('../scenario-steps/control-flow-editors.tsx', import.meta.url),
    'utf8'
  );
  const loopEditor = editorSource.slice(
    editorSource.indexOf('export function LoopConfigFields')
  );

  for (const owned of ['count', 'while', 'max_iterations']) {
    assert.ok(
      loopEditor.includes(owned),
      `LoopConfigFields no longer handles ${owned}`
    );
    assert.ok(
      !schemaFields.includes(owned),
      `${owned} is declared in both LoopConfigFields and the schema`
    );
  }

  // ...and the guards that had no editor must actually be there.
  assert.ok(schemaFields.includes('stall_after'));
  assert.ok(schemaFields.includes('idle_delay_seconds'));
  assert.ok(schemaFields.includes('loop_var'));
});

test('new loops opt into the stall guard, which is off by default at runtime', () => {
  const step = createDefaultStep('loop');

  assert.equal(step.type, 'loop');
  assert.equal(step.stall_after, 3);
});

test('tap_position offers only the positions the executors implement', () => {
  // Six of the ten options the panel used to list fell through to
  // middle_center in handle_tap_position / _tap_position_action — a silent
  // wrong tap. The list now comes from the runtime schema, after catalog
  // metadata is applied.
  const schema = readBackendScenarioSchema();
  const values = schema.steps_schema.tap_position.fields.pos.values.map(
    (option: { value: string }) => option.value
  );

  assert.deepEqual(values, [
    'top_center',
    'middle_center',
    'bottom_center',
    'search_bar'
  ]);
});

test('scan posts detail panel exposes visible like and comment toggles', () => {
  const detailSource = readFileSync(
    new URL('./step-detail-panel.tsx', import.meta.url),
    'utf8'
  );

  assert.match(detailSource, /tField\('interactionMode'\)/);
  assert.match(detailSource, /tField\('interactionLikeOption'\)/);
  assert.match(detailSource, /tField\('interactionCommentOption'\)/);
  assert.match(detailSource, /update\(\{ like_post: e\.target\.checked \}\)/);
  assert.match(
    detailSource,
    /update\(\{ require_comment: e\.target\.checked \}\)/
  );
  assert.doesNotMatch(detailSource, /socialScanInteractionMode/);
  assert.doesNotMatch(detailSource, />\\s*Like post khi match\\s*</);
});

test('flow editor renders variable lineage warnings on cards and detail panels', () => {
  const flowSource = readFileSync(
    new URL('./flow-editor.tsx', import.meta.url),
    'utf8'
  );
  const bracketSource = readFileSync(
    new URL('./bracket-block.tsx', import.meta.url),
    'utf8'
  );
  const stepCardSource = readFileSync(
    new URL('./step-card.tsx', import.meta.url),
    'utf8'
  );
  const detailSource = readFileSync(
    new URL('./step-detail-panel.tsx', import.meta.url),
    'utf8'
  );

  assert.match(flowSource, /analyzeStepVariableLineage/);
  assert.match(flowSource, /ScenarioLintSummary/);
  assert.match(flowSource, /variableLineageByPathKey/);
  assert.match(bracketSource, /lineagePath/);
  assert.match(bracketSource, /childLineage/);
  assert.match(stepCardSource, /variableLineage\?\.issues\.length/);
  assert.match(detailSource, /VariableLineageSummary/);
  assert.match(detailSource, /campaignsFeature\.stepEditor\.variableLineage/);
});

test('flow editor keeps runtime and lint technical details out of the primary copy', () => {
  const flowSource = readFileSync(
    new URL('./flow-editor.tsx', import.meta.url),
    'utf8'
  );
  const resultSource = readFileSync(
    new URL('./step-run-result.tsx', import.meta.url),
    'utf8'
  );

  assert.match(resultSource, /humanizeStepRunMessage/);
  assert.match(resultSource, /messages\.commentSheetNotOpen/);
  assert.match(resultSource, /messages\.scrollToFoundWithTarget/);
  assert.match(resultSource, /title=\{result\.message\}/);
  assert.match(resultSource, /showTechnical/);
  assert.match(resultSource, /showTechnical \? t\('hideTechnical'\)/);
  assert.match(flowSource, /summaryDescription/);
  assert.match(flowSource, /openIssue/);
  assert.match(flowSource, /issueTechnicalTitle/);
  assert.doesNotMatch(flowSource, />Lint kịch bản</);
});

test('insert picker receives capability context from root and nested flow inserts', () => {
  const flowSource = readFileSync(
    new URL('./flow-editor.tsx', import.meta.url),
    'utf8'
  );
  const bracketSource = readFileSync(
    new URL('./bracket-block.tsx', import.meta.url),
    'utf8'
  );
  const insertSource = readFileSync(
    new URL('./insert-button.tsx', import.meta.url),
    'utf8'
  );
  const flowDirectPickers = (
    flowSource.match(
      /<InsertStepPicker[\s\S]{0,320}nodeCapabilities=\{nodeCapabilities\}/g
    ) ?? []
  ).length;
  const flowInsertGaps = (
    flowSource.match(
      /<InsertGap[\s\S]{0,320}nodeCapabilities=\{nodeCapabilities\}/g
    ) ?? []
  ).length;
  const bracketInsertGaps = (
    bracketSource.match(
      /<InsertGap[\s\S]{0,240}nodeCapabilities=\{nodeCapabilities\}/g
    ) ?? []
  ).length;
  const wrapperPickers = (
    insertSource.match(
      /<InsertStepPicker[\s\S]{0,320}nodeCapabilities=\{nodeCapabilities\}/g
    ) ?? []
  ).length;

  assert.equal(flowDirectPickers, 3);
  assert.equal(flowInsertGaps, 2);
  assert.equal(bracketInsertGaps, 3);
  assert.equal(wrapperPickers, 3);
  assert.match(insertSource, /deviceCapabilities=\{deviceCapabilities\}/);
});

test('insert picker receives step-tree insert locations from root and nested flow inserts', () => {
  const flowSource = readFileSync(
    new URL('./flow-editor.tsx', import.meta.url),
    'utf8'
  );
  const bracketSource = readFileSync(
    new URL('./bracket-block.tsx', import.meta.url),
    'utf8'
  );
  const insertSource = readFileSync(
    new URL('./insert-button.tsx', import.meta.url),
    'utf8'
  );

  assert.match(flowSource, /insertLocationFromPath/);
  assert.equal(
    (
      flowSource.match(
        /<Insert(?:Gap|StepPicker)[\s\S]{0,360}insertLocation=\{/g
      ) ?? []
    ).length,
    5
  );
  assert.equal(
    (
      bracketSource.match(
        /<InsertGap[\s\S]{0,360}insertLocation=\{insertLocationForChildList/g
      ) ?? []
    ).length,
    3
  );
  assert.equal(
    (
      insertSource.match(
        /<InsertStepPicker[\s\S]{0,260}insertLocation=\{insertLocation\}/g
      ) ?? []
    ).length,
    3
  );
});

test('insert picker guidance is localized and scoped to action steps', () => {
  const pickerSource = readFileSync(
    new URL('./insert-step-picker.tsx', import.meta.url),
    'utf8'
  );

  assert.match(pickerSource, /tInsert\('pickerGuidance'/);
  assert.match(pickerSource, /category === 'actions'/);
  assert.doesNotMatch(pickerSource, /useLocale/);
  assert.doesNotMatch(
    pickerSource,
    /campaignsFeature\\.flowInsert\\.pickerGuidance/
  );
});

test('nested branch and loop trailing insert gaps stay visible', () => {
  const bracketSource = readFileSync(
    new URL('./bracket-block.tsx', import.meta.url),
    'utf8'
  );
  const flowSource = readFileSync(
    new URL('./flow-editor.tsx', import.meta.url),
    'utf8'
  );

  assert.match(
    bracketSource,
    /onInsert=\{\(s\) => onInsertChild\(listKey, steps\.length, s\)\}[\s\S]{0,180}persistent/
  );
  assert.match(flowSource, /row\.kind === 'branch' && !reorderMode/);
  assert.match(flowSource, /insertBeforePath\(row\.insertPath, step\)/);
  assert.match(flowSource, /insertLocationFromPath\(row\.insertPath\)/);
});

test('verify_screen detail editor uses cropped stored image setup', () => {
  const detailSource = readFileSync(
    new URL('./step-detail-panel.tsx', import.meta.url),
    'utf8'
  );
  const fieldSource = readFileSync(
    new URL('./verify-screen-fields.tsx', import.meta.url),
    'utf8'
  );

  assert.match(detailSource, /<VerifyScreenFields/);
  assert.doesNotMatch(
    detailSource,
    /tField\('screenshotInput'\)[\s\S]{0,160}<textarea/
  );
  assert.match(fieldSource, /ImageTemplateDialog/);
  assert.match(fieldSource, /copyScope='verifyScreen'/);
  assert.match(fieldSource, /template_key/);
  assert.match(fieldSource, /screenshot: undefined/);
});

test('step detail panel presents setup as a compact ordered flow with explicit done action', () => {
  const detailSource = readFileSync(
    new URL('./step-detail-panel.tsx', import.meta.url),
    'utf8'
  );

  assert.match(detailSource, /campaignsFeature\.stepEditor\.setupFlow/);
  assert.match(detailSource, /value=\{currentSetupTab\}/);
  assert.match(detailSource, /setSetupTab\(nextSetupTab\.value\)/);
  assert.match(detailSource, /handleDoneAndClose/);
  assert.match(detailSource, /tSetup\('done'\)/);
  assert.doesNotMatch(detailSource, /tSetup\('save'\)/);
});

test('flow editor flushes detail edits to the draft before page save', () => {
  const flowSource = readFileSync(
    new URL('./flow-editor.tsx', import.meta.url),
    'utf8'
  );

  assert.match(
    flowSource,
    /pendingDetailRef\.current = s;[\s\S]*updateAt\(selectedIndex, s\);/
  );
  assert.match(
    flowSource,
    /pendingDetailRef\.current = step;[\s\S]*updatePath\(path, step\);/
  );
});

test('tap_xml_match is available from the action insert menu', () => {
  const menu = getInsertMenuForUi((key) => key);
  const actions = menu.find((group) => group.groupKey === 'actions');

  assert.equal(
    actions?.items.some((item) => item.type === 'tap'),
    true
  );
  assert.equal(
    actions?.items.some((item) => item.type === 'tap_xml_match'),
    true
  );
  assert.equal(
    actions?.items.some((item) => item.type === 'platform_session_gate'),
    false
  );
});

test('tap_xml_match defaults match the detail editor fields', () => {
  const step = createDefaultStep('tap_xml_match');

  assert.equal(step.type, 'tap_xml_match');
  assert.equal(step.attr, 'content-desc');
  assert.equal(step.contains, '');
  assert.equal(step.clickable, true);
  assert.equal(step.timeout, 6);
  assert.equal(step.poll, 0.25);
});

test('social sync connections is exposed across editor entry points', () => {
  const detailSource = readFileSync(
    new URL('./step-detail-panel.tsx', import.meta.url),
    'utf8'
  );
  const typesSource = readFileSync(
    new URL('../scenario-steps/types.ts', import.meta.url),
    'utf8'
  );
  const platformAwareSource = readFileSync(
    new URL('./platform-aware-steps.ts', import.meta.url),
    'utf8'
  );
  const iconSource = readFileSync(
    new URL('./step-icon.tsx', import.meta.url),
    'utf8'
  );
  const menu = getInsertMenuForUi((key) => key);
  const social = menu.find((group) => group.groupKey === 'social');
  const step = createDefaultStep('social_sync_connections');

  assert.match(typesSource, /\| 'social_sync_connections'/);
  assert.match(typesSource, /case 'social_sync_connections'/);
  assert.match(platformAwareSource, /'social_sync_connections'/);
  assert.match(iconSource, /social_sync_connections: Users/);
  assert.equal(
    social?.items.some((item) => item.type === 'social_sync_connections'),
    true
  );
  assert.equal(step.type, 'social_sync_connections');
  assert.equal(step.metric, 'friends');
  assert.equal(step.persist, true);
  assert.match(detailSource, /step\.type === 'social_sync_connections'/);
  assert.match(detailSource, /socialSyncConnections\.hint/);
});

test('advanced backend-backed social and target lease fields are editable', () => {
  const detailSource = readFileSync(
    new URL('./step-detail-panel.tsx', import.meta.url),
    'utf8'
  );

  for (const key of [
    'settleSeconds',
    'candidateEntityId',
    'requireCandidateStatus',
    'candidateLeaseToken',
    'accountActionId',
    'requireCompletion',
    'completionStepsJson',
    'completionVerifyJson'
  ]) {
    assert.equal(detailSource.includes(`tField('${key}')`), true, key);
  }

  assert.match(detailSource, /leaseTarget\.actionType/);
  assert.match(detailSource, /leaseTarget\.statuses/);
  assert.match(detailSource, /step\.action_type/);
  assert.match(detailSource, /step\.statuses/);
});

for (const [locale, messages] of [
  ['en', enMessages],
  ['vi', viMessages]
] as const) {
  test(`tap_xml_match detail editor messages exist for ${locale}`, () => {
    const node = messages.campaignsFeature?.stepEditor?.tapXmlMatch;

    for (const key of [
      'hint',
      'attributeLabel',
      'attrContentDesc',
      'attrText',
      'attrResourceId',
      'attrClass',
      'matchModeLabel',
      'matchContains',
      'matchEquals',
      'valueLabel',
      'valuePlaceholder',
      'clickableLabel',
      'clickableDescription'
    ]) {
      assert.equal(typeof node?.[key], 'string', `${locale}.${key}`);
    }
  });

  test(`node capability detail editor messages exist for ${locale}`, () => {
    const node = messages.campaignsFeature?.stepEditor?.nodeCapability;

    for (const key of [
      'sectionTitle',
      'readyTitle',
      'unknownTitle',
      'missingTitle',
      'noRequirements',
      'evidenceLabel',
      'inspectorLabel'
    ]) {
      assert.equal(typeof node?.[key], 'string', `${locale}.${key}`);
    }
  });

  test(`configuration status editor messages exist for ${locale}`, () => {
    const node = messages.campaignsFeature?.stepEditor?.configurationStatus;

    for (const key of [
      'sectionTitle',
      'missingTitle',
      'warningTitle',
      'missingDescription',
      'warningDescription',
      'badgeMissing',
      'badgeWarning',
      'cardMissing',
      'cardWarning',
      'cardMissingTitle',
      'cardWarningTitle'
    ]) {
      assert.equal(typeof node?.[key], 'string', `${locale}.${key}`);
    }

    for (const key of [
      'appProfile',
      'assertionCriteria',
      'childSteps',
      'command',
      'comparisonValue',
      'condition',
      'imageTemplate',
      'localPath',
      'packageName',
      'randomBranch',
      'recipe',
      'remotePath',
      'scenarioReference',
      'screenshot',
      'selector',
      'targetConstraints',
      'text',
      'url',
      'variableKey',
      'variableName'
    ]) {
      assert.equal(typeof node?.fields?.[key], 'string', `${locale}.${key}`);
    }
  });

  test(`step setup flow messages exist for ${locale}`, () => {
    const node = messages.campaignsFeature?.stepEditor?.setupFlow;

    for (const key of [
      'title',
      'description',
      'stepNumber',
      'selectedBadge',
      'selectedAnnouncement',
      'draftBadge',
      'configure',
      'configureDescription',
      'screenDescription',
      'dataSave',
      'dataSaveDescription',
      'errorHandling',
      'errorDescription',
      'ready',
      'needsSetup',
      'next',
      'nextTo',
      'closePanel',
      'done',
      'focusHint',
      'feedbackStatus',
      'draftSafetyHint',
      'footerNextHint',
      'footerDoneHint'
    ]) {
      assert.equal(typeof node?.[key], 'string', `${locale}.${key}`);
    }
  });

  test(`verify screen image setup messages exist for ${locale}`, () => {
    const node = messages.campaignsFeature?.stepEditor?.verifyScreen;

    for (const key of [
      'referenceImage',
      'referenceHint',
      'cropFromScreen',
      'cropFromFile',
      'cropAgain',
      'noScenarioTitle',
      'noScenarioHint',
      'imageAlt',
      'loadFailed',
      'missing',
      'legacyScreenshotHint',
      'ssimThreshold',
      'ssimThresholdHint',
      'timeout',
      'poll',
      'dialogTitle',
      'dialogDescription',
      'pickFile',
      'pickAnotherFile',
      'noSource',
      'noMirrorFrame',
      'applyCrop',
      'resetCrop',
      'croppedHint',
      'cancel',
      'useImage',
      'saveFailed',
      'croppedAlt'
    ]) {
      assert.equal(typeof node?.[key], 'string', `${locale}.${key}`);
    }
  });

  test(`variable lineage editor messages exist for ${locale}`, () => {
    const node = messages.campaignsFeature?.stepEditor?.variableLineage;

    for (const key of [
      'sectionTitle',
      'badgeWarning',
      'cardWarning',
      'cardWarningTitle',
      'summaryTitle',
      'summaryDescription',
      'summaryCount',
      'summaryMore',
      'summaryFixFirst',
      'issueStepLabel',
      'openIssue',
      'issueTechnicalTitle',
      'referencesLabel',
      'producedLabel',
      'noneReferences',
      'noneProduced',
      'producerHint'
    ]) {
      assert.equal(typeof node?.[key], 'string', `${locale}.${key}`);
    }

    for (const key of [
      'unknown_reference',
      'future_reference',
      'maybe_unavailable',
      'missing_verified_target',
      'candidate_lease_without_entity',
      'source_var_without_scan',
      'verified_target_without_profile',
      'comment_flow_missing_step'
    ]) {
      assert.equal(typeof node?.issues?.[key], 'string', `${locale}.${key}`);
    }

    for (const key of [
      'unknown_reference',
      'future_reference',
      'maybe_unavailable',
      'missing_verified_target',
      'candidate_lease_without_entity',
      'source_var_without_scan',
      'verified_target_without_profile',
      'comment_flow_missing_step'
    ]) {
      assert.equal(
        typeof node?.summaryKinds?.[key],
        'string',
        `${locale}.${key}`
      );
    }
  });

  test(`step run result messages exist for ${locale}`, () => {
    const node = messages.campaignsFeature?.stepEditor?.runResult;

    for (const key of [
      'okTitle',
      'errorTitle',
      'savedTitle',
      'savedTo',
      'charCount',
      'boxCount',
      'empty',
      'expand',
      'collapse',
      'copy',
      'showTechnical',
      'hideTechnical',
      'completeFallback',
      'failedFallback',
      'previewTruncated'
    ]) {
      assert.equal(typeof node?.[key], 'string', `${locale}.${key}`);
    }

    for (const key of [
      'commentSheetNotOpen',
      'extraDataFailed',
      'scrollToFoundWithTarget',
      'scrollToFoundTargetOnly',
      'scrollToFound',
      'selectorNotFound',
      'timeout'
    ]) {
      assert.equal(typeof node?.messages?.[key], 'string', `${locale}.${key}`);
    }
  });

  test(`insert menu capability status messages exist for ${locale}`, () => {
    const node = messages.campaignsFeature?.flowInsert?.capabilityStatus;

    for (const key of ['ready', 'missing', 'unknown', 'none']) {
      assert.equal(typeof node?.[key], 'string', `${locale}.${key}`);
    }
  });

  test(`insert menu step-tree context messages exist for ${locale}`, () => {
    const node = messages.campaignsFeature?.flowInsert?.insertContext;

    for (const key of [
      'label',
      'rootSequence',
      'thenBranch',
      'elseBranch',
      'loopBody',
      'randomBranch',
      'nestedSteps'
    ]) {
      assert.equal(typeof node?.[key], 'string', `${locale}.${key}`);
    }
  });

  test(`social sync and advanced node setup messages exist for ${locale}`, () => {
    const stepEditor = messages.campaignsFeature?.stepEditor;
    const fields = stepEditor?.stepFields;
    const socialSync = stepEditor?.socialSyncConnections;
    const leaseTarget = stepEditor?.leaseTarget;
    const flowInsert = messages.campaignsFeature?.flowInsert;
    const flowStep = messages.campaignsFeature?.flowStep;

    for (const key of [
      'settleSeconds',
      'candidateEntityId',
      'requireCandidateStatus',
      'candidateLeaseToken',
      'accountActionId',
      'requireCompletion',
      'completionStepsJson',
      'completionVerifyJson',
      'metric',
      'persistMetric'
    ]) {
      assert.equal(typeof fields?.[key], 'string', `${locale}.${key}`);
    }

    for (const key of ['hint', 'persistHint']) {
      assert.equal(typeof socialSync?.[key], 'string', `${locale}.${key}`);
    }

    for (const key of ['actionType', 'statuses', 'statusesPlaceholder']) {
      assert.equal(typeof leaseTarget?.[key], 'string', `${locale}.${key}`);
    }

    assert.equal(typeof flowInsert?.itemDesc?.tap, 'string', `${locale}.tap`);
    assert.equal(
      typeof flowInsert?.pickerGuidance,
      'string',
      `${locale}.pickerGuidance`
    );
    assert.equal(
      typeof flowInsert?.itemDesc?.social_sync_connections,
      'string',
      `${locale}.social_sync_connections`
    );
    assert.equal(
      typeof flowInsert?.items?.social_sync_connections,
      'string',
      `${locale}.social_sync_connections`
    );
    assert.equal(
      typeof flowStep?.display?.socialSyncConnections,
      'string',
      `${locale}.socialSyncConnections`
    );
    assert.equal(
      typeof flowStep?.typeName?.social_sync_connections,
      'string',
      `${locale}.social_sync_connections`
    );
  });
}
