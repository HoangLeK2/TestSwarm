import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildStepLogTree,
  stepLogNodeStats,
  type StepLogNode
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './step-log-tree.ts';

type Row = {
  index: number;
  step_type: string;
  step_path: string | null;
  ok?: boolean;
  status?: 'running' | 'completed' | 'failed';
  step_id?: string;
};

function row(r: Row) {
  return {
    ok: true,
    status: 'completed' as const,
    message: null,
    depth: r.step_path ? r.step_path.split('/').length - 1 : 0,
    ...r
  };
}

function shape(nodes: StepLogNode[]): unknown[] {
  return nodes.map((node) =>
    node.kind === 'step'
      ? node.entry.step_type
      : { iter: node.iter, children: shape(node.children) }
  );
}

test('groups loop body steps under one node per iteration, in numeric order', () => {
  // Deliberately in fold order (by step, not by iteration) and with #10 before #9.
  const tree = buildStepLogTree([
    row({ index: 0, step_type: 'loop', step_path: '0', step_id: 'lp' }),
    row({ index: 0, step_type: 'tap', step_path: '0/lp#10/tap' }),
    row({ index: 0, step_type: 'tap', step_path: '0/lp#9/tap' }),
    row({ index: 1, step_type: 'wait', step_path: '0/lp#9/wait' }),
    row({ index: 1, step_type: 'wait', step_path: '0/lp#10/wait' })
  ] as never);

  assert.deepEqual(shape(tree), [
    'loop',
    { iter: 9, children: ['tap', 'wait'] },
    { iter: 10, children: ['tap', 'wait'] }
  ]);
});

test('nests an inner loop inside the outer iteration it ran in', () => {
  const tree = buildStepLogTree([
    row({ index: 0, step_type: 'tap', step_path: 'out#0/in#1/tap' }),
    row({ index: 0, step_type: 'tap', step_path: 'out#0/in#0/tap' })
  ] as never);

  assert.deepEqual(shape(tree), [
    {
      iter: 0,
      children: [
        { iter: 0, children: ['tap'] },
        { iter: 1, children: ['tap'] }
      ]
    }
  ]);
});

test('keeps pathless entries at the root and counts failures through the tree', () => {
  const tree = buildStepLogTree([
    row({ index: 0, step_type: 'preflight', step_path: null }),
    row({
      index: 1,
      step_type: 'tap',
      step_path: 'lp#0/tap',
      ok: false,
      status: 'failed'
    })
  ] as never);

  assert.equal(tree[0]?.kind, 'step');
  assert.deepEqual(stepLogNodeStats(tree), { steps: 2, failed: 1 });
});
