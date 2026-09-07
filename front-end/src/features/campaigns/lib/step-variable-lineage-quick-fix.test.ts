import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

import type { FlowStep } from '../components/scenario-steps/types.ts';
import type { StepVariableLineageIssue } from './step-variable-lineage.ts';
import {
  stepVariableLineageQuickFixes
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './step-variable-lineage-quick-fix.ts';

const require = createRequire(import.meta.url);
const enMessages = require('../../../../messages/en.json');
const viMessages = require('../../../../messages/vi.json');

const issue = (
  value: Partial<StepVariableLineageIssue> & {
    kind: StepVariableLineageIssue['kind'];
  }
): StepVariableLineageIssue => ({
  variable: value.variable ?? '_people_target',
  source: value.source ?? 'token',
  pathKey: value.pathKey ?? 'steps:1',
  ...value
});

test('quick fix fills a verified target guard for connection requests', () => {
  const fixes = stepVariableLineageQuickFixes(
    issue({
      kind: 'missing_verified_target',
      variable: '_people_target',
      source: 'require_verified_target'
    }),
    { type: 'connection_request', action: 'request' } as FlowStep
  );

  assert.deepEqual(
    fixes.find((fix) => fix.id === 'use_verified_target_guard'),
    {
      id: 'use_verified_target_guard',
      kind: 'patch_step',
      labelKey: 'quickFix.useVerifiedTargetGuard',
      descriptionKey: 'quickFix.useVerifiedTargetGuardDescription',
      patch: { require_verified_target: '_people_target' }
    }
  );
});

test('quick fix fills candidate_entity_id from an available entity variable', () => {
  const fixes = stepVariableLineageQuickFixes(
    issue({
      kind: 'candidate_lease_without_entity',
      variable: 'LEASE_TOKEN',
      source: 'candidate_lease_token'
    }),
    { type: 'candidate_take_lease' } as FlowStep,
    ['DISPLAY_NAME', 'TARGET_ENTITY_ID']
  );

  assert.deepEqual(
    fixes.find((fix) => fix.id === 'use_candidate_entity_id'),
    {
      id: 'use_candidate_entity_id',
      kind: 'patch_step',
      labelKey: 'quickFix.useCandidateEntityId',
      descriptionKey: 'quickFix.useCandidateEntityIdDescription',
      patch: { candidate_entity_id: '${TARGET_ENTITY_ID}' }
    }
  );
});

test('quick fix falls back to guidance when lease entity context is missing', () => {
  const fixes = stepVariableLineageQuickFixes(
    issue({
      kind: 'candidate_lease_without_entity',
      variable: 'LEASE_TOKEN',
      source: 'candidate_lease_token'
    }),
    { type: 'candidate_take_lease' } as FlowStep,
    ['DISPLAY_NAME']
  );

  assert.deepEqual(
    fixes.map((fix) => fix.kind),
    ['guidance']
  );
  assert.equal(fixes[0]?.labelKey, 'quickFix.addCandidateEntityId');
});

test('quick fix inserts a missing comment-flow step before the current step', () => {
  const fixes = stepVariableLineageQuickFixes(
    issue({
      kind: 'comment_flow_missing_step',
      variable: 'social_tap_comment_target',
      source: 'runtime_step'
    }),
    { type: 'social_comment' } as FlowStep
  );
  const fix = fixes.find(
    (candidate) => candidate.kind === 'insert_step_before'
  );

  assert.equal(fix?.id, 'insert_social_tap_comment_target');
  assert.equal(fix?.labelKey, 'quickFix.insertRequiredStep');
  assert.equal(fix?.kind, 'insert_step_before');
  if (fix?.kind === 'insert_step_before') {
    assert.equal(fix.step.type, 'social_tap_comment_target');
  }
});

test('quick fix patches profile opener source_var to the default post scan output', () => {
  const fixes = stepVariableLineageQuickFixes(
    issue({
      kind: 'source_var_without_scan',
      variable: '_post_scan',
      source: 'source_var'
    }),
    { type: 'open_profile', source_var: 'POSTS' } as FlowStep
  );

  assert.deepEqual(
    fixes.find((fix) => fix.id === 'use_default_post_scan_source'),
    {
      id: 'use_default_post_scan_source',
      kind: 'patch_step',
      labelKey: 'quickFix.useDefaultPostScanSource',
      descriptionKey: 'quickFix.useDefaultPostScanSourceDescription',
      patch: { source_var: '_post_scan' }
    }
  );
});

test('quick fix exposes producer navigation when lineage knows the producer path', () => {
  const fixes = stepVariableLineageQuickFixes(
    issue({
      kind: 'future_reference',
      variable: 'PROFILE_ID',
      producerPathKey: 'steps:3',
      producerStepType: 'social_select_target'
    }),
    { type: 'input_text', text: '${PROFILE_ID}' } as FlowStep
  );

  assert.deepEqual(
    fixes.map((fix) => fix.id),
    ['select_producer', 'move_producer_before_guidance']
  );
});

test('quick fix can insert a set_variable step for unknown variables', () => {
  const fixes = stepVariableLineageQuickFixes(
    issue({
      kind: 'unknown_reference',
      variable: 'PROFILE_ID'
    }),
    { type: 'input_text', text: '${PROFILE_ID}' } as FlowStep
  );
  const fix = fixes.find((candidate) => candidate.id === 'insert_set_variable');

  assert.equal(fix?.kind, 'insert_step_before');
  if (fix?.kind === 'insert_step_before') {
    assert.equal(fix.step.type, 'set_variable');
    assert.equal(fix.step.name, 'PROFILE_ID');
    assert.equal(fix.step.value, '');
  }
  assert.equal(
    fixes.some((candidate) => candidate.id === 'declare_variable_guidance'),
    true
  );
});

test('quick fix can insert a profile target selector for unverified target sources', () => {
  const fixes = stepVariableLineageQuickFixes(
    issue({
      kind: 'verified_target_without_profile',
      variable: '_people_target',
      source: 'require_verified_target'
    }),
    {
      type: 'connection_request',
      action: 'request',
      require_verified_target: '_people_target'
    } as FlowStep
  );
  const fix = fixes.find(
    (candidate) => candidate.id === 'insert_profile_target_selector'
  );

  assert.equal(fix?.kind, 'insert_step_before');
  if (fix?.kind === 'insert_step_before') {
    assert.equal(fix.step.type, 'social_select_target');
    assert.equal(fix.step.target_type, 'person');
    assert.equal(fix.step.save_as, '_people_target');
  }
});

test('flow editor wires quick fixes into detail panels and card severity', () => {
  const flowSource = readFileSync(
    new URL('../components/flow-editor/flow-editor.tsx', import.meta.url),
    'utf8'
  );
  const detailSource = readFileSync(
    new URL('../components/flow-editor/step-detail-panel.tsx', import.meta.url),
    'utf8'
  );
  const stepCardSource = readFileSync(
    new URL('../components/flow-editor/step-card.tsx', import.meta.url),
    'utf8'
  );

  assert.match(flowSource, /onInsertStepBefore=\{\(newStep\) =>/);
  assert.match(flowSource, /onSelectVariableLineagePathKey/);
  assert.equal(
    (flowSource.match(/onRepairIssue=\{applyScenarioLintRepair\}/g) ?? [])
      .length,
    2
  );
  assert.match(flowSource, /firstScenarioLintRepairFix/);
  assert.match(flowSource, /summaryFixFirst/);
  assert.match(flowSource, /shiftPathTail/);
  assert.match(detailSource, /stepVariableLineageQuickFixes/);
  assert.match(detailSource, /applyVariableLineageQuickFix/);
  assert.match(stepCardSource, /scenarioLintIssueSeverity/);
  assert.match(stepCardSource, /cardCritical/);
});

test('quick fix labels are translated in English and Vietnamese', () => {
  for (const messages of [enMessages, viMessages]) {
    const lineage = messages.campaignsFeature.stepEditor.variableLineage;

    assert.equal(typeof lineage.badgeCritical, 'string');
    assert.equal(typeof lineage.cardCritical, 'string');
    assert.equal(typeof lineage.summaryRepairCount, 'string');
    assert.equal(typeof lineage.summaryFixFirst, 'string');
    assert.deepEqual(Object.keys(lineage.quickFix).sort(), [
      'addCandidateEntityId',
      'addCandidateEntityIdDescription',
      'declareVariable',
      'declareVariableDescription',
      'goToProducer',
      'goToProducerDescription',
      'insertProfileTargetSelector',
      'insertProfileTargetSelectorDescription',
      'insertRequiredStep',
      'insertRequiredStepDescription',
      'insertSetVariable',
      'insertSetVariableDescription',
      'moveProducerBefore',
      'moveProducerBeforeDescription',
      'replaceTargetSource',
      'replaceTargetSourceDescription',
      'useCandidateEntityId',
      'useCandidateEntityIdDescription',
      'useDefaultPostScanSource',
      'useDefaultPostScanSourceDescription',
      'useVerifiedTargetGuard',
      'useVerifiedTargetGuardDescription'
    ]);
  }
});
