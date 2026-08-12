import assert from 'node:assert/strict';
import test from 'node:test';

import {
  canDropScenarioNodes
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './drag-drop-rules.ts';

type TestNode = {
  id: string;
  flowNodeType: string;
  parent?: TestNode;
};

function node(id: string, flowNodeType: string, parent?: TestNode): TestNode {
  return { id, flowNodeType, parent };
}

const root = node('$root', 'root');
const start = node('start_0', 'start', root);
const condition = node('condition', 'condition', root);
const inlineBlocks = node('$inlineBlocks$condition', 'inlineBlocks', condition);
const thenBlock = node('condition_then', 'block', inlineBlocks);
const elseBlock = node('condition_else', 'block', inlineBlocks);
const thenIcon = node(
  '$blockOrderIcon$condition_then',
  'blockOrderIcon',
  thenBlock
);
const elseIcon = node(
  '$blockOrderIcon$condition_else',
  'blockOrderIcon',
  elseBlock
);
const thenChild = node('then-child', 'action', thenBlock);
const elseChild = node('else-child', 'action', elseBlock);

const loop = node('loop', 'loop_node', root);
const loopInlineBlocks = node('$inlineBlocks$loop', 'inlineBlocks', loop);
const loopBlock = node('$block$loop', 'block', loopInlineBlocks);
const loopEmpty = node('$loopRightEmpty$loop', 'loopEmptyBranch', loopBlock);
const loopChild = node('loop-child', 'action', loopBlock);

test('allows root reorder and root-to-root movement anchors', () => {
  const action = node('action', 'action', root);

  assert.equal(
    canDropScenarioNodes({ dragNodes: [action], dropNode: start }),
    true
  );
});

test('allows dropping into empty then/else branch anchors', () => {
  const action = node('action', 'action', root);

  assert.equal(
    canDropScenarioNodes({ dragNodes: [action], dropNode: thenIcon }),
    true
  );
  assert.equal(
    canDropScenarioNodes({ dragNodes: [action], dropNode: elseIcon }),
    true
  );
});

test('allows dropping into populated branches and moving branch-to-branch', () => {
  const action = node('action', 'action', root);

  assert.equal(
    canDropScenarioNodes({ dragNodes: [action], dropNode: thenChild }),
    true
  );
  assert.equal(
    canDropScenarioNodes({ dragNodes: [thenChild], dropNode: elseChild }),
    true
  );
});

test('allows dropping into empty and populated loop bodies', () => {
  const action = node('action', 'action', root);

  assert.equal(
    canDropScenarioNodes({ dragNodes: [action], dropNode: loopEmpty }),
    true
  );
  assert.equal(
    canDropScenarioNodes({ dragNodes: [action], dropNode: loopChild }),
    true
  );
});

test('allows moving nested nodes back to the root sequence', () => {
  assert.equal(
    canDropScenarioNodes({ dragNodes: [thenChild], dropNode: start }),
    true
  );
  assert.equal(
    canDropScenarioNodes({ dragNodes: [loopChild], dropNode: condition }),
    true
  );
});

test('rejects scenario containers moved into their own descendants', () => {
  assert.equal(
    canDropScenarioNodes({ dragNodes: [condition], dropNode: thenIcon }),
    false
  );
  assert.equal(
    canDropScenarioNodes({ dragNodes: [loop], dropNode: loopEmpty }),
    false
  );
});

test('rejects system drag nodes and invalid destination parents', () => {
  const action = node('action', 'action', root);

  assert.equal(
    canDropScenarioNodes({ dragNodes: [start], dropNode: condition }),
    false
  );
  assert.equal(
    canDropScenarioNodes({ dragNodes: [thenIcon], dropNode: condition }),
    false
  );
  assert.equal(
    canDropScenarioNodes({ dragNodes: [action], dropNode: condition }),
    true
  );
  assert.equal(
    canDropScenarioNodes({ dragNodes: [action], dropNode: inlineBlocks }),
    false
  );
});

test('rejects the end sentinel as an insertion anchor', () => {
  const action = node('action', 'action', root);
  const end = node('end_0', 'end', root);

  assert.equal(
    canDropScenarioNodes({ dragNodes: [action], dropNode: end }),
    false
  );
});
