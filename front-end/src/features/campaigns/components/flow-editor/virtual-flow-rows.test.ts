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
      row.kind === 'step' ? row.step.type : row.label
    ]),
    [
      ['step', 'if_variable'],
      ['branch', 'NẾU ĐÚNG'],
      ['step', 'wait'],
      ['branch', 'NẾU SAI'],
      ['end', 'KẾT THÚC IF']
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
    rows.at(-1)?.kind === 'end' && rows.at(-1).label,
    'KẾT THÚC VÒNG LẶP'
  );
});
