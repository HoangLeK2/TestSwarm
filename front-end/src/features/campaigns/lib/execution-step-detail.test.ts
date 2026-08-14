import assert from 'node:assert/strict';
import test from 'node:test';

import {
  executionStepDetail
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './execution-step-detail.ts';

test('uses scenario name instead of a run_scenario UUID', () => {
  const detail = executionStepDetail({
    step_index: 1,
    step_type: 'run_scenario',
    step_id: '3ed0fe60-e854-48f3-8f61-78cd1b9b6995',
    trace: { scenario_name: 'Kiểm tra phiên Facebook' },
    effective_config_json: {},
    id: 'step-1',
    execution_id: 'execution-1',
    status: 'failed',
    error_json: {},
    artifacts_json: [],
    attempts_json: [],
    marked_ignored: false,
    created_at: '',
    updated_at: ''
  });

  assert.equal(detail.label, 'Kiểm tra phiên Facebook');
  assert.equal(detail.reference, 'run_scenario');
});

test('flattens nested step results for step-by-step display', () => {
  const detail = executionStepDetail({
    step_index: 1,
    trace: {
      sub_results: [
        {
          step_type: 'if_variable',
          message: 'then branch failed',
          ok: false,
          step_results: [{ step_type: 'tap', ok: true }]
        }
      ]
    },
    effective_config_json: {},
    id: 'step-1',
    execution_id: 'execution-1',
    status: 'failed',
    error_json: {},
    artifacts_json: [],
    attempts_json: [],
    marked_ignored: false,
    created_at: '',
    updated_at: ''
  });

  assert.deepEqual(
    detail.nested.map(({ label, status }) => ({ label, status })),
    [
      { label: 'if_variable', status: 'failed' },
      { label: 'tap', status: 'completed' }
    ]
  );
});
