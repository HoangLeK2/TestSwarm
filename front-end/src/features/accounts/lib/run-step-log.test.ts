import assert from 'node:assert/strict';
import test from 'node:test';

import {
  runEventsToLogEntries,
  runStepToLogEntry,
  runStepsToLogEntries
} from './run-step-log.ts';
import type { AccountRunEventOut, AccountRunStepOut } from '../services/api.ts';

function step(over: Partial<AccountRunStepOut> = {}): AccountRunStepOut {
  return {
    id: 'row-1',
    execution_id: 'exec-1',
    step_index: 0,
    step_id: 's0',
    step_type: 'tap_selector',
    status: 'passed',
    started_at: '2026-09-13T10:00:00Z',
    ended_at: '2026-09-13T10:00:01Z',
    duration_ms: 1000,
    error_json: {},
    effective_config_json: {},
    artifacts_json: [],
    attempts_json: [],
    marked_ignored: false,
    message: 'tap_selector Comment',
    ...over
  };
}

test('prefers the account-facing sentence over the raw step message', () => {
  const entry = runStepToLogEntry(
    step({
      effective_config_json: {
        trace: {
          depth: 0,
          step_path: 's0',
          action: {
            semantic_action: 'comment.section_open',
            activity_summary: 'Opened the comment section on Post A'
          }
        }
      }
    })
  );

  assert.equal(entry.message, 'Opened the comment section on Post A');
  // The raw message is kept, not replaced: a failure needs both.
  assert.equal(entry.details?.raw_message, 'tap_selector Comment');
  assert.equal(entry.details?.semantic_action, 'comment.section_open');
});

test('falls back to the step message when no semantic action was recorded', () => {
  const entry = runStepToLogEntry(step());
  assert.equal(entry.message, 'tap_selector Comment');
  assert.equal(entry.ok, true);
  assert.equal(entry.status, 'completed');
});

test('carries the failure reason a ban investigation looks for', () => {
  const entry = runStepToLogEntry(
    step({
      status: 'failed',
      message: 'connection_request: add-friend button not found',
      error_json: { reason_code: 'ELEMENT_NOT_FOUND', failure_class: 'ui' }
    })
  );

  assert.equal(entry.ok, false);
  assert.equal(entry.status, 'failed');
  assert.equal(entry.reason_code, 'ELEMENT_NOT_FOUND');
  assert.equal(entry.details?.failure_class, 'ui');
});

test('skipped steps read as completed, not failed', () => {
  // status "skipped" is what a resumed checkpoint writes. Showing it red would
  // send an investigation after a step that never ran.
  const entry = runStepToLogEntry(step({ status: 'skipped' }));
  assert.equal(entry.ok, true);
  assert.equal(entry.status, 'completed');
});

test('keeps loop position so repeated steps stay distinguishable', () => {
  const entry = runStepToLogEntry(
    step({
      effective_config_json: {
        trace: { depth: 2, loop_id: 'loop-1', loop_iter: 7, branch: 'then' }
      }
    })
  );

  assert.equal(entry.depth, 2);
  assert.equal(entry.loop_iter, 7);
  assert.equal(entry.loop_id, 'loop-1');
  assert.equal(entry.branch, 'then');
});

test('orders by step_index regardless of the order rows arrive in', () => {
  const entries = runStepsToLogEntries([
    step({ step_index: 2, step_id: 's2' }),
    step({ step_index: 0, step_id: 's0' }),
    step({ step_index: 1, step_id: 's1' })
  ]);

  assert.deepEqual(
    entries.map((e) => e.index),
    [0, 1, 2]
  );
});

test('survives a row whose trace is missing or malformed', () => {
  const entry = runStepToLogEntry(
    step({
      step_type: null,
      effective_config_json: { trace: 'not an object' as unknown as object }
    })
  );

  assert.equal(entry.step_type, '');
  assert.equal(entry.depth, 0);
  assert.equal(entry.loop_iter, null);
});

function ev(over: Partial<AccountRunEventOut> = {}): AccountRunEventOut {
  return {
    event_id: 'e1',
    event_type: 'step.completed',
    occurred_at: '2026-09-13T10:00:00Z',
    step_id: 's0',
    payload: {},
    ...over
  };
}

test('a started/completed pair renders as one row, not two', () => {
  const entries = runEventsToLogEntries([
    ev({ event_id: 'a', event_type: 'step.started' }),
    ev({ event_id: 'b', event_type: 'step.completed' })
  ]);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].ok, true);
});

test('loop iterations stay in occurrence order, not index order', () => {
  // The same step repeats its index on every iteration; only step_path carries
  // the iteration. Sorting by index would interleave the iterations.
  const mk = (iter: number, at: string) =>
    ev({
      event_id: `i${iter}`,
      occurred_at: at,
      payload: {
        step_index: 0,
        step_type: 'scroll_down',
        depth: 2,
        trace: { step_path: `0/loop#${iter}/scroll`, loop_iter: iter, depth: 2 }
      }
    });
  const entries = runEventsToLogEntries([
    mk(2, '2026-09-13T10:00:02Z'),
    mk(1, '2026-09-13T10:00:01Z'),
    mk(3, '2026-09-13T10:00:03Z')
  ]);
  assert.deepEqual(
    entries.map((e) => e.loop_iter),
    [1, 2, 3]
  );
  assert.deepEqual(
    entries.map((e) => e.step_path),
    ['0/loop#1/scroll', '0/loop#2/scroll', '0/loop#3/scroll']
  );
});

test('nested depth survives so the tree can be rendered', () => {
  const [entry] = runEventsToLogEntries([
    ev({
      payload: {
        step_type: 'tap_selector',
        depth: 3,
        trace: { depth: 3, branch: 'then', step_path: '0/a.else/b.then/c' }
      }
    })
  ]);
  assert.equal(entry.depth, 3);
  assert.equal(entry.branch, 'then');
});

test('step.failed carries the reason a ban investigation needs', () => {
  const [entry] = runEventsToLogEntries([
    ev({
      event_type: 'step.failed',
      payload: {
        step_type: 'connection_request',
        ok: false,
        message: 'add-friend button not found',
        reason_code: 'ELEMENT_NOT_FOUND'
      }
    })
  ]);
  assert.equal(entry.ok, false);
  assert.equal(entry.status, 'failed');
  assert.equal(entry.reason_code, 'ELEMENT_NOT_FOUND');
});

test('non-step events are ignored', () => {
  const entries = runEventsToLogEntries([
    ev({ event_type: 'execution.started' }),
    ev({ event_type: 'temporal.activity.completed' }),
    ev({ event_type: 'incident.detected' })
  ]);
  assert.deepEqual(entries, []);
});
