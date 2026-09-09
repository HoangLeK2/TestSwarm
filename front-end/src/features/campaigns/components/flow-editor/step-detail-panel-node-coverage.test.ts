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

test('scan posts detail panel exposes visible like and comment toggles', () => {
  const detailSource = readFileSync(
    new URL('./step-detail-panel.tsx', import.meta.url),
    'utf8'
  );

  assert.match(detailSource, /tField\('interactionMode'\)/);
  assert.match(detailSource, /tField\('interactionLikeOption'\)/);
  assert.match(detailSource, /tField\('interactionCommentOption'\)/);
  assert.match(detailSource, /update\(\{ like_post: e\.target\.checked \}\)/);
  assert.match(detailSource, /update\(\{ require_comment: e\.target\.checked \}\)/);
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
      'done',
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
}
