import assert from 'node:assert/strict';
import test from 'node:test';
import {
  primaryProducedVariable,
  variablesProducedByStep
} from './step-produced-variables.ts';
import type { FlowStep } from '../scenario-steps/types.ts';

const step = (s: Record<string, unknown>) => s as unknown as FlowStep;

test('OCR exposes its save_as so later steps can use it', () => {
  const produced = variablesProducedByStep(
    step({ type: 'extract_text_ocr', save_as: 'ocr_text' })
  );
  assert.deepEqual(produced, ['ocr_text']);
  assert.equal(
    primaryProducedVariable(
      step({ type: 'extract_text_ocr', save_as: 'ocr_text' })
    ),
    'ocr_text'
  );
});

test('select target exposes both the target and the success flag', () => {
  const produced = variablesProducedByStep(
    step({
      type: 'social_select_target',
      save_as: '_people_target',
      save_success_as: 'PEOPLE_PROFILE_SELECTED'
    })
  );
  assert.deepEqual(produced.sort(), [
    'PEOPLE_PROFILE_SELECTED',
    '_people_target'
  ]);
});

test('lease step exposes its fixed candidate variables', () => {
  const produced = variablesProducedByStep(
    step({ type: 'lease_connection_candidate' })
  );
  assert.ok(produced.includes('CANDIDATE_NAME'));
  assert.ok(produced.includes('TARGET_ENTITY_ID'));
});

test('session gate exposes the readiness flag', () => {
  assert.deepEqual(
    variablesProducedByStep(step({ type: 'platform_session_gate' })),
    ['PLATFORM_SESSION_READY']
  );
});

test('source pool expands the configured output prefix', () => {
  const produced = variablesProducedByStep(
    step({ type: 'use_source_pool', output_prefix: 'PAGE' })
  );
  assert.ok(produced.includes('PAGE_ENTITY_ID'));
  assert.ok(produced.includes('PAGE_NAME'));
  assert.ok(!produced.some((n) => n.startsWith('GROUP_')));
});

test('source pool falls back to the GROUP prefix', () => {
  const produced = variablesProducedByStep(step({ type: 'use_source_pool' }));
  assert.ok(produced.includes('GROUP_ENTITY_ID'));
});

test('a ${VAR} reference is not treated as a new variable', () => {
  assert.deepEqual(
    variablesProducedByStep(
      step({ type: 'extract_text_ocr', save_as: '${SOME_VAR}' })
    ),
    []
  );
  assert.equal(
    primaryProducedVariable(
      step({ type: 'extract_text_ocr', save_as: '${SOME_VAR}' })
    ),
    null
  );
});

test('steps that write nothing produce nothing', () => {
  assert.deepEqual(variablesProducedByStep(step({ type: 'tap' })), []);
  assert.equal(primaryProducedVariable(step({ type: 'tap' })), null);
  assert.equal(
    primaryProducedVariable(step({ type: 'platform_session_gate' })),
    null,
    'fixed-name producers have no single "result" to chain from'
  );
});

test('loop exposes its loop variable', () => {
  assert.deepEqual(
    variablesProducedByStep(step({ type: 'loop', loop_var: 'i' })),
    ['i']
  );
});
