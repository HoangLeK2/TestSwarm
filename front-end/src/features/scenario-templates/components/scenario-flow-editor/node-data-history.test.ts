import assert from 'node:assert/strict';
import test from 'node:test';

import {
  UPDATE_SCENARIO_NODE_DATA,
  applyUpdateScenarioNodeDataOperation,
  createUpdateScenarioNodeDataOperation,
  invertUpdateScenarioNodeDataOperation,
  mergeUpdateScenarioNodeDataOperations
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './node-data-history.ts';

function operation(nodeId: string, oldTitle: string, newTitle: string) {
  return createUpdateScenarioNodeDataOperation(
    nodeId,
    { step: { id: nodeId, type: 'wait', title: oldTitle } },
    { step: { id: nodeId, type: 'wait', title: newTitle } }
  );
}

test('node data history inverse swaps old and new data', () => {
  const original = operation('wait-1', 'Before', 'After');
  const inverse = invertUpdateScenarioNodeDataOperation(original);

  assert.equal(inverse.type, UPDATE_SCENARIO_NODE_DATA);
  assert.deepEqual(inverse.value, {
    nodeId: 'wait-1',
    oldData: original.value.newData,
    newData: original.value.oldData
  });
});

test('rapid updates for the same node merge into one undo item', () => {
  const first = operation('wait-1', 'Before', 'Middle');
  const second = operation('wait-1', 'Middle', 'After');
  const merged = mergeUpdateScenarioNodeDataOperations(second, first, 300);

  assert.notEqual(merged, false);
  assert.deepEqual(merged && merged.value, {
    nodeId: 'wait-1',
    oldData: first.value.oldData,
    newData: second.value.newData
  });
});

test('updates do not merge across nodes or outside the merge window', () => {
  const first = operation('wait-1', 'Before', 'After');

  assert.equal(
    mergeUpdateScenarioNodeDataOperations(
      operation('wait-2', 'Before', 'After'),
      first,
      100
    ),
    false
  );
  assert.equal(
    mergeUpdateScenarioNodeDataOperations(
      operation('wait-1', 'After', 'Later'),
      first,
      801
    ),
    false
  );
});

test('applying node data update preserves the canonical node id', () => {
  let applied: Record<string, unknown> | null = null;
  const ctx = {
    document: {
      getNode(id: string) {
        if (id !== 'wait-1') return undefined;
        return {
          updateExtInfo(data: Record<string, unknown>) {
            applied = data;
          }
        };
      }
    }
  };
  const update = operation('wait-1', 'Before', 'After');

  assert.equal(
    applyUpdateScenarioNodeDataOperation(update, ctx as never),
    true
  );
  const appliedData = applied as Record<string, unknown> | null;
  assert.equal(
    (appliedData?.['step'] as Record<string, unknown> | undefined)?.['id'],
    'wait-1'
  );
  assert.equal(
    applyUpdateScenarioNodeDataOperation(
      operation('missing', 'Before', 'After'),
      ctx as never
    ),
    false
  );
});
