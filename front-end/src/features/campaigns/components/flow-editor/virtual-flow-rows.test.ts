import assert from 'node:assert/strict';
import test from 'node:test';
import type { FlowStep } from '../scenario-steps/types';
import { projectVirtualFlowRows } from './virtual-flow-rows.ts';

test('projects explicit branches and end marker for an if block', () => {
  const steps: FlowStep[] = [
    {
      type: 'if_variable',
      then: [{ type: 'wait', seconds: 1 }],
      else: []
    }
  ];

  const rows = projectVirtualFlowRows(steps);

  assert.deepEqual(
    rows.map((row) => [
      row.kind,
      row.kind === 'step' ? row.step.type : row.labelKey
    ]),
    [
      ['step', 'if_variable'],
      ['branch', 'branchIfTrue'],
      ['step', 'wait'],
      ['branch', 'branchIfFalse'],
      ['end', 'branchIfEnd']
    ]
  );
  assert.equal(rows[3]?.kind === 'branch' && rows[3].count, 0);
});

test('keeps nested scope ancestry on virtual rows', () => {
  const steps: FlowStep[] = [
    {
      type: 'loop',
      steps: [
        {
          type: 'if_variable',
          then: [{ type: 'wait', seconds: 1 }],
          else: []
        }
      ]
    }
  ];

  const rows = projectVirtualFlowRows(steps);
  const waitRow = rows.find(
    (row) => row.kind === 'step' && row.step.type === 'wait'
  );

  assert.equal(waitRow?.scopes.length, 2);
  assert.deepEqual(
    waitRow?.scopes.map((scope) => scope.type),
    ['loop', 'if_variable']
  );
  assert.equal(rows.at(-1)?.kind, 'end');
  assert.equal(
    rows.at(-1)?.kind === 'end' && rows.at(-1).labelKey,
    'branchLoopEnd'
  );
});

test('branch rows carry their meaning, not their wording', () => {
  // The flow marker used to be chosen by substring-matching the Vietnamese
  // label, so translating the label silently turned every "then" branch into
  // a loop marker. Meaning lives in `branch` now; wording lives in `labelKey`.
  const rows = projectVirtualFlowRows([
    { type: 'if_variable', then: [{ type: 'wait', seconds: 1 }], else: [] },
    { type: 'loop', steps: [{ type: 'wait', seconds: 1 }] }
  ] as FlowStep[]);

  const branches = rows
    .filter((row) => row.kind === 'branch')
    .map((row) => (row.kind === 'branch' ? row.branch : null));

  assert.deepEqual(branches, ['then', 'else', 'loop']);
});

test('branch rows expose append insert paths for loop, if, and random branches', () => {
  const rows = projectVirtualFlowRows([
    { type: 'loop', steps: [] },
    { type: 'if_variable', then: [], else: [{ type: 'wait', seconds: 1 }] },
    {
      type: 'random_pick',
      branches: [
        { weight: 1, steps: [] },
        { weight: 1, steps: [{ type: 'wait', seconds: 2 }] }
      ]
    }
  ] as FlowStep[]);

  const branchPaths = rows
    .filter((row) => row.kind === 'branch')
    .map((row) => (row.kind === 'branch' ? row.insertPath : []));

  assert.deepEqual(branchPaths, [
    [
      { listKey: 'steps', ci: 0 },
      { listKey: 'steps', ci: 0 }
    ],
    [
      { listKey: 'steps', ci: 1 },
      { listKey: 'then', ci: 0 }
    ],
    [
      { listKey: 'steps', ci: 1 },
      { listKey: 'else', ci: 1 }
    ],
    [
      { listKey: 'steps', ci: 2 },
      { listKey: 'branches.0', ci: 0 }
    ],
    [
      { listKey: 'steps', ci: 2 },
      { listKey: 'branches.1', ci: 1 }
    ]
  ]);
});
