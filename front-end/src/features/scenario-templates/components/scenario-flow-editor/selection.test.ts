import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getSingleEditableFlowNodeId
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './selection.ts';

function entity(id: string, flowNodeType: string) {
  return { id, flowNodeType };
}

test('selection bridge returns a single editable node ID', () => {
  for (const type of ['action', 'sub_scenario', 'condition', 'loop_node']) {
    assert.equal(
      getSingleEditableFlowNodeId([entity(`${type}-id`, type)]),
      `${type}-id`
    );
  }
});

test('selection bridge hides detail for empty and multi-selection', () => {
  assert.equal(getSingleEditableFlowNodeId([]), null);
  assert.equal(
    getSingleEditableFlowNodeId([
      entity('first', 'action'),
      entity('second', 'action')
    ]),
    null
  );
});

test('selection bridge ignores structural Flowgram nodes', () => {
  for (const type of ['start', 'end', 'block', 'blockIcon', 'blockOrderIcon']) {
    assert.equal(
      getSingleEditableFlowNodeId([entity(`${type}-id`, type)]),
      null
    );
  }
  assert.equal(getSingleEditableFlowNodeId([{ id: 'missing-type' }]), null);
});
