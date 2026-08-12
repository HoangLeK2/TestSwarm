import assert from 'node:assert/strict';
import test from 'node:test';

import type { FlowNodeJSON } from '@flowgram.ai/fixed-layout-editor';
import {
  parseScenarioClipboardNodes,
  regenerateScenarioClipboardNodeIds,
  serializeScenarioClipboardNodes
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './clipboard.ts';

const nestedNode: FlowNodeJSON = {
  id: 'condition-1',
  type: 'condition',
  data: {
    step: {
      id: 'condition-1',
      _fgId: 'condition-1',
      type: 'if_element',
      then: [],
      else: []
    }
  },
  blocks: [
    {
      id: 'condition-1_then',
      type: 'block',
      data: { title: 'Then' },
      blocks: [
        {
          id: 'wait-1',
          type: 'action',
          data: {
            step: {
              id: 'wait-1',
              _fgId: 'wait-1',
              type: 'wait'
            }
          }
        }
      ]
    },
    {
      id: 'condition-1_else',
      type: 'block',
      data: { title: 'Else' },
      blocks: []
    }
  ]
};

test('scenario clipboard round trip rejects unrelated text', () => {
  assert.deepEqual(
    parseScenarioClipboardNodes(serializeScenarioClipboardNodes([nestedNode])),
    [nestedNode]
  );
  assert.equal(parseScenarioClipboardNodes('not-json'), null);
  assert.equal(parseScenarioClipboardNodes('{"nodes":[]}'), null);
});

test('pasted nodes regenerate canonical and structural IDs recursively', () => {
  const generated = ['condition-copy', 'wait-copy'];
  const copies = regenerateScenarioClipboardNodeIds(
    [nestedNode],
    () => generated.shift()!
  );
  const condition = copies[0]!;
  const thenBlock = condition.blocks?.[0];
  const wait = thenBlock?.blocks?.[0];

  assert.equal(condition.id, 'condition-copy');
  assert.equal(condition.data?.step.id, 'condition-copy');
  assert.equal(condition.data?.step._fgId, 'condition-copy');
  assert.equal(thenBlock?.id, 'condition-copy_then');
  assert.equal(condition.blocks?.[1]?.id, 'condition-copy_else');
  assert.equal(wait?.id, 'wait-copy');
  assert.equal(wait?.data?.step.id, 'wait-copy');
  assert.equal(wait?.data?.step._fgId, 'wait-copy');
});

test('clipboard regeneration does not mutate copied nodes', () => {
  const before = JSON.parse(JSON.stringify(nestedNode));
  regenerateScenarioClipboardNodeIds([nestedNode], () => 'copy');
  assert.deepEqual(nestedNode, before);
});
