import assert from 'node:assert/strict';
import test from 'node:test';
import { foldEventsToStepLog } from './execution-event-utils.ts';

test('foldEventsToStepLog keeps adb shell output fields from step event payload', () => {
  const rows = foldEventsToStepLog([
    {
      event_id: 'evt-1',
      event_type: 'step.completed',
      execution_id: 'exec-1',
      payload: {
        step_index: 0,
        step_type: 'adb_shell',
        ok: true,
        message: 'adb_shell exit=0',
        output: 'Pixel 7\n',
        exit_code: 0,
        save_as: 'PHONE_MODEL',
        output_truncated: false
      }
    } as any
  ]);

  assert.equal(rows.length, 1);
  assert.equal(rows[0].step_type, 'adb_shell');
  assert.equal(rows[0].output, 'Pixel 7\n');
  assert.equal(rows[0].exit_code, 0);
  assert.equal(rows[0].save_as, 'PHONE_MODEL');
  assert.equal(rows[0].output_truncated, false);
});
