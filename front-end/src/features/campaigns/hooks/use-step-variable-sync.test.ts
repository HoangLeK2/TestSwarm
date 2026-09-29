import assert from 'node:assert/strict';
import test from 'node:test';

import { analyzeStepVariableLineage } from '../lib/step-variable-lineage.ts';
import { syncScenarioVariablesWithStepReferences } from '../../../lib/scenario-variable-references.ts';

test('all node tokens become declarations unless a node produces them', () => {
  const steps = [
    { type: 'input_text', text: '${SEARCH_QUERY}' },
    { type: 'extract_text_ocr', save_as: 'OCR_TEXT' },
    { type: 'input_text', text: '${OCR_TEXT}' },
    {
      type: 'loop',
      count: '${MAX_SCROLLS}',
      steps: [{ type: 'input_text', text: '${NESTED_TEXT}' }]
    }
  ];
  const produced = new Set(analyzeStepVariableLineage(steps).allProduced);
  const result = syncScenarioVariablesWithStepReferences(
    [],
    steps,
    {},
    new Set(),
    produced
  );

  assert.deepEqual(result.variables, {
    MAX_SCROLLS: '',
    NESTED_TEXT: '',
    SEARCH_QUERY: ''
  });
  assert.equal('OCR_TEXT' in result.variables, false);
});

test('direct runtime variable fields are not mistaken for scenario inputs', () => {
  const steps = [
    { type: 'social_select_target', save_as: '_post_target' },
    {
      type: 'content_interaction',
      require_verified_target: '_post_target'
    },
    { type: 'if_variable', name: '_post_target' }
  ];
  const produced = new Set(analyzeStepVariableLineage(steps).allProduced);
  const result = syncScenarioVariablesWithStepReferences(
    [],
    steps,
    {},
    new Set(),
    produced
  );

  assert.deepEqual(result.variables, {});
});
