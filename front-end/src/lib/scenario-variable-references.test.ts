import assert from 'node:assert/strict';
import test from 'node:test';

import {
  collectScenarioVariableReferences,
  syncScenarioVariablesWithStepReferences
} from './scenario-variable-references.ts';

test('collectScenarioVariableReferences finds tokens in nested scenario bodies', () => {
  assert.deepEqual(
    collectScenarioVariableReferences({
      steps: [
        {
          type: 'loop',
          count: '${PAGE_COUNT}',
          steps: [
            { type: 'input_text', text: '${SEARCH_QUERY}' },
            {
              type: 'set_variable',
              from_list: '${PAGE_TARGETS}',
              literal: 'PAGE_TARGETS'
            }
          ]
        }
      ]
    }),
    ['PAGE_COUNT', 'PAGE_TARGETS', 'SEARCH_QUERY']
  );
});

test('syncScenarioVariablesWithStepReferences creates variables for new references', () => {
  const result = syncScenarioVariablesWithStepReferences(
    [],
    [{ type: 'content_interaction', comment_text: '${COMMENT_TEXT}' }],
    {},
    new Set()
  );

  assert.deepEqual(result.variables, { COMMENT_TEXT: '' });
  assert.deepEqual([...result.managedNames], ['COMMENT_TEXT']);
});

test('syncScenarioVariablesWithStepReferences removes only auto-created unused variables', () => {
  const result = syncScenarioVariablesWithStepReferences(
    [
      { text: '${COMMENT_TEXT}' },
      { text: '${SHARED_TEXT}' },
      { text: '${USER_TEXT}' }
    ],
    [{ text: '${SHARED_TEXT}' }],
    {
      COMMENT_TEXT: 'hello',
      SHARED_TEXT: 'shared',
      USER_TEXT: 'keep me'
    },
    new Set(['COMMENT_TEXT', 'SHARED_TEXT'])
  );

  assert.deepEqual(result.variables, {
    SHARED_TEXT: 'shared',
    USER_TEXT: 'keep me'
  });
  assert.deepEqual([...result.managedNames], ['SHARED_TEXT']);
});

test('syncScenarioVariablesWithStepReferences preserves pre-existing variables', () => {
  const result = syncScenarioVariablesWithStepReferences(
    [],
    [{ text: '${COMMENT_TEXT}' }],
    { COMMENT_TEXT: 'existing value' },
    new Set()
  );

  assert.deepEqual(result.variables, { COMMENT_TEXT: 'existing value' });
  assert.deepEqual([...result.managedNames], []);
});

test('syncScenarioVariablesWithStepReferences does not declare produced variables', () => {
  const result = syncScenarioVariablesWithStepReferences(
    [],
    [
      { type: 'extract_text_ocr', save_as: 'OCR_TEXT' },
      { type: 'input_text', text: '${OCR_TEXT}' }
    ],
    {},
    new Set(),
    new Set(['OCR_TEXT'])
  );

  assert.deepEqual(result.variables, {});
  assert.deepEqual([...result.managedNames], []);
});

test('syncScenarioVariablesWithStepReferences removes an auto variable once a node produces it', () => {
  const result = syncScenarioVariablesWithStepReferences(
    [{ type: 'input_text', text: '${OCR_TEXT}' }],
    [
      { type: 'extract_text_ocr', save_as: 'OCR_TEXT' },
      { type: 'input_text', text: '${OCR_TEXT}' }
    ],
    { OCR_TEXT: '' },
    new Set(['OCR_TEXT']),
    new Set(['OCR_TEXT'])
  );

  assert.deepEqual(result.variables, {});
  assert.deepEqual([...result.managedNames], []);
});
