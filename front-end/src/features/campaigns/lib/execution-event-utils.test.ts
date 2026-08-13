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

test('foldEventsToStepLog keeps app automation monitor details', () => {
  const rows = foldEventsToStepLog([
    {
      event_id: 'evt-app-1',
      event_type: 'step.completed',
      execution_id: 'exec-1',
      payload: {
        step_index: 3,
        step_type: 'fill_form',
        message: 'fill_form: completed basic',
        app_popup_watchers: [
          {
            name: 'close_update',
            executed: true,
            message: "tapped text 'Later'"
          }
        ],
        form_fields: {
          email: {
            matched: true,
            locator_name: 'email_field',
            score: 0.9,
            reason: 'resource_id_contains match'
          }
        },
        submit_trace: {
          matched: true,
          locator_name: 'submit_text',
          score: 1,
          reason: "text='Save'"
        }
      }
    } as any
  ]);

  assert.equal(rows.length, 1);
  assert.equal(rows[0].step_type, 'fill_form');
  assert.deepEqual(rows[0].details?.app_popup_watchers, [
    {
      name: 'close_update',
      executed: true,
      message: "tapped text 'Later'"
    }
  ]);
  assert.deepEqual(rows[0].details?.form_fields, {
    email: {
      matched: true,
      locator_name: 'email_field',
      score: 0.9,
      reason: 'resource_id_contains match'
    }
  });
  assert.deepEqual(rows[0].details?.submit_trace, {
    matched: true,
    locator_name: 'submit_text',
    score: 1,
    reason: "text='Save'"
  });
});

test('foldEventsToStepLog attaches incident events to the owning step', () => {
  const rows = foldEventsToStepLog([
    {
      event_id: 'evt-1',
      event_type: 'incident.detected',
      execution_id: 'exec-1',
      payload: {
        step_index: 2,
        step_type: 'fb_comment',
        incident_type: 'facebook_popup',
        confidence: 0.9,
        matched_rule: true
      }
    } as any,
    {
      event_id: 'evt-2',
      event_type: 'step.completed',
      execution_id: 'exec-1',
      payload: {
        step_index: 2,
        step_type: 'fb_comment',
        message: 'ok'
      }
    } as any
  ]);

  assert.equal(rows.length, 1);
  assert.equal(rows[0].index, 2);
  assert.equal(rows[0].step_type, 'fb_comment');
  assert.equal(rows[0].incidents?.length, 1);
  assert.equal(rows[0].incidents?.[0]?.event_type, 'incident.detected');
  assert.equal(rows[0].incidents?.[0]?.incident_type, 'facebook_popup');
  assert.equal(rows[0].incidents?.[0]?.matched_rule, true);
});

test('foldEventsToStepLog keeps recovery scenario metadata on incident events', () => {
  const rows = foldEventsToStepLog([
    {
      event_id: 'evt-1',
      event_type: 'incident.recovery.started',
      execution_id: 'exec-1',
      payload: {
        step_index: 4,
        step_type: 'fb_comment',
        incident_type: 'profile_page',
        attempt: 2,
        scenario_id: 'main-scenario',
        recovery_scenario_id: 'recovery-scenario',
        recovery_scenario_name: 'Close profile popup',
        incident_key: '4:loop-12',
        rule_id: 'rule-profile',
        outcome: 'retry_step'
      }
    } as any
  ]);

  assert.equal(rows.length, 1);
  assert.equal(rows[0].incidents?.length, 1);
  assert.equal(rows[0].incidents?.[0]?.event_type, 'incident.recovery.started');
  assert.equal(rows[0].incidents?.[0]?.attempt, 2);
  assert.equal(rows[0].incidents?.[0]?.scenario_id, 'main-scenario');
  assert.equal(
    rows[0].incidents?.[0]?.recovery_scenario_id,
    'recovery-scenario'
  );
  assert.equal(
    rows[0].incidents?.[0]?.recovery_scenario_name,
    'Close profile popup'
  );
  assert.equal(rows[0].incidents?.[0]?.incident_key, '4:loop-12');
  assert.equal(rows[0].incidents?.[0]?.rule_id, 'rule-profile');
  assert.equal(rows[0].incidents?.[0]?.outcome, 'retry_step');
});

test('foldEventsToStepLog exposes step.started as a running row for live UI spinners', () => {
  const rows = foldEventsToStepLog([
    {
      event_id: 'evt-1',
      event_type: 'step.started',
      execution_id: 'exec-1',
      step_id: 'if-1',
      payload: {
        step_index: 1,
        step_id: 'if-1',
        step_type: 'if_element',
        depth: 2,
        message: 'running if'
      }
    } as any
  ]);

  assert.equal(rows.length, 1);
  assert.equal(rows[0].index, 1);
  assert.equal(rows[0].step_id, 'if-1');
  assert.equal(rows[0].step_type, 'if_element');
  assert.equal(rows[0].depth, 2);
  assert.equal(rows[0].status, 'running');
  assert.equal(rows[0].message, 'running if');
});

test('foldEventsToStepLog preserves every repeated step occurrence and action proof', () => {
  const events = [1, 2].flatMap((iteration) => [
    {
      event_id: `started-${iteration}`,
      event_type: 'step.started',
      execution_id: 'exec-1',
      step_id: 'batch-like',
      payload: {
        step_index: 4,
        step_id: 'batch-like',
        step_type: 'content_interaction',
        depth: 2,
        trace: {
          scenario_name: 'Scenario A',
          account_id: 'account-1'
        }
      }
    },
    {
      event_id: `completed-${iteration}`,
      event_type: 'step.completed',
      execution_id: 'exec-1',
      step_id: 'batch-like',
      payload: {
        step_index: 4,
        step_id: 'batch-like',
        step_type: 'content_interaction',
        depth: 2,
        display_name: `Post ${iteration}`,
        outcome: 'applied',
        action_performed: true,
        account_action_id: `action-${iteration}`,
        trace: {
          scenario_name: 'Scenario A',
          account_id: 'account-1',
          action: {
            account_action_id: `action-${iteration}`
          }
        }
      }
    }
  ]);

  const rows = foldEventsToStepLog(events as any);

  assert.equal(rows.length, 2);
  assert.notEqual(rows[0].occurrence_key, rows[1].occurrence_key);
  assert.deepEqual(
    rows.map((row) => row.details?.display_name),
    ['Post 1', 'Post 2']
  );
  assert.deepEqual(
    rows.map((row) => row.details?.account_action_id),
    ['action-1', 'action-2']
  );
  assert.deepEqual(
    rows.map((row) => row.trace?.scenario_name),
    ['Scenario A', 'Scenario A']
  );
  assert.deepEqual(
    rows.map((row) => row.trace?.account_id),
    ['account-1', 'account-1']
  );
});
