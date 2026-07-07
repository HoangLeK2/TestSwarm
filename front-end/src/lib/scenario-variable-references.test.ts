import assert from 'node:assert/strict';
import test from 'node:test';

import {
  detectSingleVariableRename,
  replaceScenarioVariableReferences,
  stripUndeclaredVariableReferencesFromTags
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './scenario-variable-references.ts';

test('detectSingleVariableRename returns the one removed and added variable key', () => {
  assert.deepEqual(
    detectSingleVariableRename(
      { GROUP_NAME: 'OpenClaw', SAVE_COLLECTION: 'posts' },
      { TARGET_GROUP_NAME: 'OpenClaw', SAVE_COLLECTION: 'posts' }
    ),
    { from: 'GROUP_NAME', to: 'TARGET_GROUP_NAME' }
  );
});

test('detectSingleVariableRename ignores add/remove and invalid variable names', () => {
  assert.equal(detectSingleVariableRename({ GROUP_NAME: 'x' }, {}), null);
  assert.equal(
    detectSingleVariableRename({ GROUP_NAME: 'x' }, { 'target-group': 'x' }),
    null
  );
});

test('replaceScenarioVariableReferences updates nested string values only', () => {
  const input = {
    type: 'loop',
    GROUP_NAME: 'object key is not a runtime token',
    steps: [
      { type: 'input_text', text: '${GROUP_NAME}' },
      {
        type: 'extract',
        tags: 'group,crawl,${GROUP_NAME}',
        untouched: '${GROUP_NAME_EXTRA}'
      }
    ]
  };

  assert.deepEqual(
    replaceScenarioVariableReferences(input, {
      from: 'GROUP_NAME',
      to: 'TARGET_GROUP_NAME'
    }),
    {
      type: 'loop',
      GROUP_NAME: 'object key is not a runtime token',
      steps: [
        { type: 'input_text', text: '${TARGET_GROUP_NAME}' },
        {
          type: 'extract',
          tags: 'group,crawl,${TARGET_GROUP_NAME}',
          untouched: '${GROUP_NAME_EXTRA}'
        }
      ]
    }
  );
});

test('stripUndeclaredVariableReferencesFromTags removes only stale tag tokens', () => {
  const input = [
    {
      type: 'extract',
      tags: 'group,crawl,${GROUP_NAME},${demo}',
      text: '${GROUP_NAME}'
    }
  ];

  assert.deepEqual(
    stripUndeclaredVariableReferencesFromTags(input, { demo: 'x' }),
    [
      {
        type: 'extract',
        tags: 'group,crawl,${demo}',
        text: '${GROUP_NAME}'
      }
    ]
  );
});
