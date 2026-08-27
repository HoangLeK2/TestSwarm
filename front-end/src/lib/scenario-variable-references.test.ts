import assert from 'node:assert/strict';
import test from 'node:test';

import { collectScenarioVariableReferences } from './scenario-variable-references.ts';

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
