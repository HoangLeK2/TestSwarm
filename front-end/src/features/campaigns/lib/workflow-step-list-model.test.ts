import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildWorkflowStepRows,
  deriveWorkflowCursor,
  flattenWorkflowSteps,
  mergeStepLogEntries,
  normalizeTemporalStepLogEntry,
  resolveCurrentRootIndex
} from './workflow-step-list-model.ts';
import type { FlowStep } from '../components/scenario-steps/types.ts';
import type { StepLogEntry } from '../types.ts';

test('flattenWorkflowSteps includes nested if/else and loop body steps', () => {
  const steps = [
    { id: 'tap-1', type: 'tap' },
    {
      id: 'if-1',
      type: 'if_element',
      then: [{ id: 'open-1', type: 'open_app' }],
      else: [
        {
          id: 'loop-1',
          type: 'loop',
          steps: [{ id: 'tap-2', type: 'tap' }]
        }
      ]
    }
  ] as FlowStep[];

  const flat = flattenWorkflowSteps(steps);

  assert.deepEqual(
    flat.map((row) => ({
      id: (row.step as { id?: string }).id,
      depth: row.depth,
      branch: row.branchLabel,
      rootIndex: row.rootIndex,
      localIndex: row.localIndex
    })),
    [
      { id: 'tap-1', depth: 0, branch: undefined, rootIndex: 0, localIndex: 0 },
      { id: 'if-1', depth: 0, branch: undefined, rootIndex: 1, localIndex: 1 },
      {
        id: 'open-1',
        depth: 1,
        branch: 'monitorStepBranchThen',
        rootIndex: 1,
        localIndex: 0
      },
      {
        id: 'loop-1',
        depth: 1,
        branch: 'monitorStepBranchElse',
        rootIndex: 1,
        localIndex: 0
      },
      {
        id: 'tap-2',
        depth: 2,
        branch: 'monitorStepBranchLoop',
        rootIndex: 1,
        localIndex: 0
      }
    ]
  );
});

test('buildWorkflowStepRows marks prior rows done, active row running, and future rows pending', () => {
  const steps = [
    { id: 'tap-1', type: 'tap' },
    {
      id: 'if-1',
      type: 'if_element',
      then: [{ id: 'open-1', type: 'open_app' }]
    },
    { id: 'tap-2', type: 'tap' }
  ] as FlowStep[];
  const logs: StepLogEntry[] = [
    {
      index: 0,
      step_type: 'tap',
      ok: true,
      message: null,
      depth: 0,
      status: 'completed'
    }
  ];

  const rows = buildWorkflowStepRows({
    scenarioSteps: steps,
    executedSteps: logs,
    currentRootIndex: 1,
    isActive: true
  });

  assert.equal(rows.length, 4);
  assert.equal(rows[0].status, 'completed');
  assert.equal(rows[1].status, 'running');
  assert.equal(rows[2].status, 'pending');
  assert.equal(rows[3].status, 'pending');
  assert.equal(rows.completedCount, 1);
  assert.equal(rows.totalCount, 4);
});

test('buildWorkflowStepRows marks every displayed row completed for a completed workflow', () => {
  const rows = buildWorkflowStepRows({
    scenarioSteps: [
      {
        id: 'loop-1',
        type: 'loop',
        steps: [{ id: 'tap-1', type: 'tap' }]
      },
      { id: 'open-1', type: 'open_app' }
    ] as FlowStep[],
    executedSteps: [],
    currentRootIndex: 0,
    isActive: false,
    isCompleted: true
  });

  assert.equal(rows.length, 3);
  assert.deepEqual(
    rows.map((row) => row.status),
    ['completed', 'completed', 'completed']
  );
  assert.equal(rows.completedCount, 3);
});

test('buildWorkflowStepRows maps running logs to nested rows by step id', () => {
  const rows = buildWorkflowStepRows({
    scenarioSteps: [
      {
        id: 'if-1',
        type: 'if_element',
        then: [{ id: 'tap-nested', type: 'tap' }]
      }
    ] as FlowStep[],
    executedSteps: [
      {
        index: 0,
        step_id: 'tap-nested',
        step_type: 'tap',
        ok: true,
        message: 'tap running',
        depth: 1,
        status: 'running'
      }
    ],
    currentRootIndex: 0,
    isActive: true
  });

  assert.equal(rows[0].status, 'running');
  assert.equal(rows[1].status, 'running');
  assert.equal(rows[1].pathKey, 'steps.0.then.0');
  assert.equal(rows[1].logEntry?.step_id, 'tap-nested');
});

test('buildWorkflowStepRows maps nested loop logs by trace step path', () => {
  const rows = buildWorkflowStepRows({
    scenarioSteps: [
      {
        id: 'gate',
        type: 'if_variable',
        then: [
          {
            id: 'cycle',
            type: 'loop',
            steps: [{ id: 'mark', type: 'set_variable' }]
          }
        ],
        else: [{ id: 'mark', type: 'set_variable' }]
      }
    ] as FlowStep[],
    executedSteps: [
      {
        index: 0,
        step_id: 'mark',
        step_type: 'set_variable',
        ok: true,
        message: null,
        depth: 2,
        status: 'completed',
        trace: {
          step_path: 'gate.then/cycle#2/mark',
          loop_iter: 2,
          branch: 'then'
        }
      }
    ],
    currentRootIndex: 0,
    isActive: true
  });

  const completed = rows.find((row) => row.status === 'completed');

  assert.equal(completed?.pathKey, 'steps.0.then.0.steps.0');
  assert.equal(completed?.tracePath, 'gate.then/cycle/mark');
  assert.equal(completed?.logEntry?.trace?.step_path, 'gate.then/cycle#2/mark');
});

test('normalizeTemporalStepLogEntry promotes persisted trace fields', () => {
  const row = normalizeTemporalStepLogEntry({
    step_index: 1,
    step_type: 'set_variable',
    status: 'completed',
    trace: {
      step_path: 'gate.then/cycle#1/mark',
      loop_id: 'cycle',
      loop_iter: 1,
      branch: 'then'
    },
    reason_code: 'ok'
  });

  assert.equal(row.step_path, 'gate.then/cycle#1/mark');
  assert.equal(row.loop_id, 'cycle');
  assert.equal(row.loop_iter, 1);
  assert.equal(row.branch, 'then');
  assert.equal(row.reason_code, 'ok');
});

test('normalizeTemporalStepLogEntry preserves persisted runtime evidence', () => {
  const row = normalizeTemporalStepLogEntry({
    step_index: 2,
    step_type: 'extract_text_ocr',
    status: 'failed',
    evidence: {
      reason_code: 'node_capability_preflight_failed',
      device_serial: 'phone-001',
      missing_capabilities: ['has_ocr', 'has_tesseract']
    }
  });

  assert.equal(row.evidence?.reason_code, 'node_capability_preflight_failed');
  assert.equal(row.evidence?.device_serial, 'phone-001');
  assert.deepEqual(row.evidence?.missing_capabilities, [
    'has_ocr',
    'has_tesseract'
  ]);
});

test('deriveWorkflowCursor advances past completed root logs when workflow is active', () => {
  const cursor = deriveWorkflowCursor({
    isActive: true,
    executedSteps: [
      {
        index: 0,
        step_type: 'stop_app',
        ok: true,
        message: null,
        depth: 0
      },
      {
        index: 1,
        step_type: 'launch_app',
        ok: true,
        message: null,
        depth: 0
      },
      {
        index: 2,
        step_type: 'if_element',
        ok: true,
        message: null,
        depth: 0
      },
      {
        index: 3,
        step_type: 'tap',
        ok: true,
        message: null,
        depth: 0
      }
    ]
  });

  assert.equal(cursor.currentRootIndex, 4);
});

test('mergeStepLogEntries prefers running status and combines sources', () => {
  const merged = mergeStepLogEntries(
    [
      {
        index: 0,
        step_type: 'stop_app',
        ok: true,
        message: null,
        depth: 0,
        status: 'completed'
      }
    ],
    [
      {
        index: 1,
        step_type: 'launch_app',
        ok: true,
        message: null,
        depth: 0,
        status: 'completed'
      },
      {
        index: 2,
        step_type: 'tap',
        ok: true,
        message: null,
        depth: 0,
        status: 'running'
      }
    ]
  );

  assert.equal(merged.length, 3);
  assert.equal(merged[2].status, 'running');
});

test('mergeStepLogEntries keeps Temporal activity events when status source changes', () => {
  const merged = mergeStepLogEntries(
    [
      {
        index: 0,
        step_id: 'tap-1',
        step_type: 'tap',
        ok: true,
        message: 'running',
        depth: 0,
        status: 'running',
        temporal_activity_events: [
          {
            event_type: 'temporal.activity.scheduled',
            state: 'scheduled',
            activity_id: 'activity-1',
            activity_attempt: 1
          }
        ]
      }
    ],
    [
      {
        index: 0,
        step_id: 'tap-1',
        step_type: 'tap',
        ok: true,
        message: 'done',
        depth: 0,
        status: 'completed',
        temporal_activity_events: [
          {
            event_type: 'temporal.activity.completed',
            state: 'completed',
            activity_id: 'activity-1',
            activity_attempt: 1,
            duration_ms: 900
          }
        ]
      }
    ]
  );

  assert.equal(merged.length, 1);
  assert.equal(merged[0].status, 'completed');
  assert.deepEqual(
    merged[0].temporal_activity_events?.map((event) => event.state),
    ['scheduled', 'completed']
  );
});

test('resolveCurrentRootIndex ignores stale zero progress when logs advanced', () => {
  const current = resolveCurrentRootIndex({
    isActive: true,
    progressCurrentStep: 0,
    executedSteps: [
      {
        index: 0,
        step_type: 'stop_app',
        ok: true,
        message: null,
        depth: 0
      },
      {
        index: 1,
        step_type: 'launch_app',
        ok: true,
        message: null,
        depth: 0
      },
      {
        index: 2,
        step_type: 'tap',
        ok: true,
        message: null,
        depth: 0
      },
      {
        index: 3,
        step_type: 'input_text',
        ok: true,
        message: null,
        depth: 0
      }
    ]
  });

  assert.equal(current, 4);
});

test('buildWorkflowStepRows marks the next root step running when prior logs completed', () => {
  const rows = buildWorkflowStepRows({
    scenarioSteps: [
      { id: 'stop', type: 'stop_app' },
      { id: 'open', type: 'launch_app' },
      { id: 'tap', type: 'tap' },
      { id: 'input', type: 'input_text' },
      { id: 'key', type: 'key' }
    ] as FlowStep[],
    executedSteps: [
      {
        index: 0,
        step_type: 'stop_app',
        ok: true,
        message: null,
        depth: 0
      },
      {
        index: 1,
        step_type: 'launch_app',
        ok: true,
        message: null,
        depth: 0
      },
      {
        index: 2,
        step_type: 'tap',
        ok: true,
        message: null,
        depth: 0
      },
      {
        index: 3,
        step_type: 'input_text',
        ok: true,
        message: null,
        depth: 0
      }
    ],
    currentRootIndex: 4,
    isActive: true
  });

  assert.equal(rows[0].status, 'completed');
  assert.equal(rows[3].status, 'completed');
  assert.equal(rows[4].status, 'running');
});

test('flattenWorkflowSteps labels run_scenario children as scenario steps', () => {
  const flat = flattenWorkflowSteps([
    {
      id: 'scenario-1',
      type: 'run_scenario',
      steps: [{ id: 'tap-child', type: 'tap' }]
    }
  ] as FlowStep[]);

  assert.equal(flat.length, 2);
  assert.equal(flat[0].branchLabel, undefined);
  assert.equal(flat[1].branchLabel, 'monitorStepBranchScenario');
  assert.equal(flat[1].depth, 1);
});

test('normalizeTemporalStepLogEntry maps persisted failed status to failed row', () => {
  const row = normalizeTemporalStepLogEntry({
    step_index: 7,
    step_type: 'social_like',
    status: 'failed',
    message: 'selector timeout',
    trace: { account_id: 'acc-1' }
  });

  assert.equal(row.index, 7);
  assert.equal(row.ok, false);
  assert.equal(row.status, 'failed');
  assert.equal(row.trace?.account_id, 'acc-1');
});
