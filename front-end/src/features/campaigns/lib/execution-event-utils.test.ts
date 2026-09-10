import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  foldEventsToProgress,
  foldEventsToStepLog
} from './execution-event-utils.ts';

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

test('foldEventsToStepLog attaches Temporal activity events to the owning step', () => {
  const rows = foldEventsToStepLog([
    {
      event_id: 'evt-step-started',
      event_type: 'step.started',
      execution_id: 'exec-1',
      step_id: 'tap-1',
      occurred_at: '2026-09-05T01:00:00.000Z',
      payload: {
        step_index: 1,
        step_id: 'tap-1',
        step_type: 'tap',
        message: 'running tap'
      }
    } as any,
    {
      event_id: 'evt-activity-scheduled',
      event_type: 'temporal.activity.scheduled',
      execution_id: 'exec-1',
      step_id: 'tap-1',
      occurred_at: '2026-09-05T01:00:01.000Z',
      payload: {
        step_index: 1,
        step_id: 'tap-1',
        step_type: 'tap',
        temporal_activity: true,
        activity_id: 'exec-1.tap-1.attempt-1',
        step_activity_id: 'tap-1.attempt-1',
        side_effect_class: 'device_write',
        activity_attempt: 1,
        phase: 'scheduled'
      }
    } as any,
    {
      event_id: 'evt-activity-stalled',
      event_type: 'temporal.activity.stalled',
      execution_id: 'exec-1',
      step_id: 'tap-1',
      occurred_at: '2026-09-05T01:00:31.000Z',
      payload: {
        step_index: 1,
        step_id: 'tap-1',
        step_type: 'tap',
        temporal_activity: true,
        activity_id: 'exec-1.tap-1.attempt-1',
        step_activity_id: 'tap-1.attempt-1',
        side_effect_class: 'device_write',
        activity_attempt: 1,
        phase: 'stalled',
        duration_ms: 30000,
        stalled_reason: 'temporal_activity_timeout'
      }
    } as any,
    {
      event_id: 'evt-step-completed',
      event_type: 'step.completed',
      execution_id: 'exec-1',
      step_id: 'tap-1',
      occurred_at: '2026-09-05T01:00:32.000Z',
      payload: {
        step_index: 1,
        step_id: 'tap-1',
        step_type: 'tap',
        message: 'tap ok'
      }
    } as any
  ]);

  assert.equal(rows.length, 1);
  assert.equal(rows[0].status, 'completed');
  assert.deepEqual(
    rows[0].temporal_activity_events?.map((event) => event.state),
    ['scheduled', 'stalled']
  );
  assert.equal(
    rows[0].temporal_activity_events?.[0]?.activity_id,
    'exec-1.tap-1.attempt-1'
  );
  assert.equal(
    rows[0].temporal_activity_events?.[1]?.stalled_reason,
    'temporal_activity_timeout'
  );
});

test('foldEventsToStepLog exposes orphan Temporal activity failures as synthetic rows', () => {
  const rows = foldEventsToStepLog([
    {
      event_id: 'evt-activity-failed',
      event_type: 'temporal.activity.failed',
      execution_id: 'exec-1',
      step_id: 'login-1',
      occurred_at: '2026-09-05T01:05:00.000Z',
      payload: {
        step_index: 2,
        step_id: 'login-1',
        step_type: 'launch_app',
        temporal_activity: true,
        activity_id: 'exec-1.login-1.attempt-2',
        side_effect_class: 'device_lifecycle',
        activity_attempt: 2,
        phase: 'failed',
        duration_ms: 1200,
        ok: false,
        message: 'activity timed out'
      }
    } as any
  ]);

  assert.equal(rows.length, 1);
  assert.equal(rows[0].index, 2);
  assert.equal(rows[0].step_id, 'login-1');
  assert.equal(rows[0].step_type, 'launch_app');
  assert.equal(rows[0].status, 'failed');
  assert.equal(rows[0].ok, false);
  assert.equal(rows[0].temporal_activity_events?.[0]?.state, 'failed');
  assert.equal(rows[0].temporal_activity_events?.[0]?.activity_attempt, 2);
});

test('foldEventsToStepLog does not let late activity events downgrade terminal rows', () => {
  const rows = foldEventsToStepLog([
    {
      event_id: 'evt-step-started',
      event_type: 'step.started',
      execution_id: 'exec-1',
      step_id: 'tap-1',
      payload: {
        step_index: 0,
        step_id: 'tap-1',
        step_type: 'tap'
      }
    } as any,
    {
      event_id: 'evt-step-completed',
      event_type: 'step.completed',
      execution_id: 'exec-1',
      step_id: 'tap-1',
      payload: {
        step_index: 0,
        step_id: 'tap-1',
        step_type: 'tap',
        message: 'tap ok'
      }
    } as any,
    {
      event_id: 'evt-activity-stalled',
      event_type: 'temporal.activity.stalled',
      execution_id: 'exec-1',
      step_id: 'tap-1',
      occurred_at: '2026-09-05T01:00:31.000Z',
      payload: {
        step_index: 0,
        step_id: 'tap-1',
        step_type: 'tap',
        activity_id: 'activity-late',
        phase: 'stalled',
        stalled_reason: 'temporal_activity_timeout'
      }
    } as any
  ]);

  assert.equal(rows.length, 1);
  assert.equal(rows[0].status, 'completed');
  assert.equal(rows[0].temporal_activity_events?.[0]?.state, 'stalled');
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

test('foldEventsToStepLog and progress expose scenario step trace fields', () => {
  const events = [
    {
      event_id: 'evt-1',
      event_type: 'step.started',
      execution_id: 'exec-1',
      step_id: 'mark',
      payload: {
        step_index: 0,
        step_id: 'mark',
        step_type: 'set_variable',
        depth: 2,
        trace: {
          step_id: 'mark',
          step_path: 'gate.then/cycle#3/mark',
          loop_id: 'cycle',
          loop_iter: 3,
          branch: 'then'
        }
      }
    },
    {
      event_id: 'evt-2',
      event_type: 'step.failed',
      execution_id: 'exec-1',
      step_id: 'mark',
      payload: {
        step_index: 0,
        step_id: 'mark',
        step_type: 'set_variable',
        depth: 2,
        reason_code: 'loop_iteration_failed',
        trace: {
          step_id: 'mark',
          step_path: 'gate.then/cycle#3/mark',
          loop_id: 'cycle',
          loop_iter: 3,
          branch: 'then'
        }
      }
    }
  ] as any;

  const rows = foldEventsToStepLog(events);
  const progress = foldEventsToProgress(events, 'workflow-1', 'serial-1');

  assert.equal(rows.length, 1);
  assert.equal(rows[0].step_path, 'gate.then/cycle#3/mark');
  assert.equal(rows[0].loop_id, 'cycle');
  assert.equal(rows[0].loop_iter, 3);
  assert.equal(rows[0].branch, 'then');
  assert.equal(rows[0].reason_code, 'loop_iteration_failed');
  assert.equal(progress?.current_step_id, 'mark');
  assert.equal(progress?.current_step_path, 'gate.then/cycle#3/mark');
  assert.equal(progress?.current_loop_iter, 3);
  assert.equal(progress?.reason_code, 'loop_iteration_failed');
  assert.equal(progress?.loop_iteration, 3);
});

test('foldEventsToStepLog preserves runtime evidence for monitor rows', () => {
  const rows = foldEventsToStepLog([
    {
      event_id: 'evt-evidence',
      event_type: 'step.failed',
      execution_id: 'exec-1',
      step_id: 'ocr-1',
      payload: {
        step_index: 1,
        step_id: 'ocr-1',
        step_type: 'extract_text_ocr',
        ok: false,
        message: 'OCR unavailable',
        reason_code: 'node_capability_preflight_failed',
        evidence: {
          reason_code: 'node_capability_preflight_failed',
          device_serial: 'phone-001',
          scenario_name: 'OCR scenario',
          missing_capabilities: ['has_ocr', 'has_tesseract'],
          node_capability_preflight: {
            ok: false,
            issues: [
              {
                path: 'steps[1]',
                step_type: 'extract_text_ocr',
                missing: ['has_ocr', 'has_tesseract']
              }
            ]
          }
        }
      }
    } as any
  ]);

  assert.equal(rows.length, 1);
  assert.equal(rows[0].reason_code, 'node_capability_preflight_failed');
  assert.equal(rows[0].evidence?.device_serial, 'phone-001');
  assert.deepEqual(rows[0].evidence?.missing_capabilities, [
    'has_ocr',
    'has_tesseract'
  ]);
});

test('fold events expose execution failed preflight evidence without step rows', () => {
  const events = [
    {
      event_id: 'evt-execution-failed',
      event_type: 'execution.failed',
      execution_id: 'exec-1',
      payload: {
        reason_code: 'node_capability_preflight_failed',
        message: 'node capability preflight failed at steps[0]',
        evidence: {
          reason_code: 'node_capability_preflight_failed',
          device_serial: 'phone-001',
          missing_capabilities: ['has_ocr']
        }
      }
    } as any
  ];
  const progress = foldEventsToProgress(events, 'exec_exec-1', 'phone-001');
  const rows = foldEventsToStepLog(events);

  assert.equal(progress?.status, 'failed');
  assert.equal(
    progress?.message,
    'node capability preflight failed at steps[0]'
  );
  assert.equal(progress?.reason_code, 'node_capability_preflight_failed');
  assert.equal(rows.length, 1);
  assert.equal(rows[0].status, 'failed');
  assert.equal(rows[0].step_type, 'preflight');
  assert.equal(rows[0].evidence?.device_serial, 'phone-001');
});

test('runtime evidence monitor labels are localized and rendered from i18n', () => {
  const source = readFileSync(
    new URL('../components/workflow-step-list.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /RuntimeEvidencePanel/);
  assert.match(source, /monitorEvidenceTitle/);
  assert.doesNotMatch(source, /Runtime evidence/);

  for (const locale of ['en', 'vi']) {
    const messages = JSON.parse(
      readFileSync(
        new URL(`../../../../messages/${locale}.json`, import.meta.url),
        'utf8'
      )
    );
    const list = messages.campaignsFeature?.list ?? {};
    for (const key of [
      'monitorEvidenceTitle',
      'monitorEvidenceReason',
      'monitorEvidenceClass',
      'monitorEvidenceRetry',
      'monitorEvidenceOperator',
      'monitorEvidenceDevice',
      'monitorEvidenceScenario',
      'monitorEvidenceAccount',
      'monitorEvidenceStepPath',
      'monitorEvidenceMissing',
      'monitorTemporalActivityEvent',
      'monitorTemporalActivityOlder',
      'monitorTemporalActivityScheduled',
      'monitorTemporalActivityRetrying',
      'monitorTemporalActivityCompleted',
      'monitorTemporalActivityFailed',
      'monitorTemporalActivityStalled'
    ]) {
      assert.equal(typeof list[key], 'string', `${locale}.${key}`);
    }
  }
});

test('foldEventsToStepLog folds a retried step the same way whichever order the batch arrives in', () => {
  // Same six events, two delivery orders: interleaved (what the timeline says)
  // and batched (workflow telemetry flushed after the step already reported).
  const stepEvent = (
    id: string,
    type: string,
    at: string,
    extra: Record<string, unknown> = {}
  ) =>
    ({
      event_id: id,
      event_type: type,
      execution_id: 'exec-1',
      step_id: 'wait-1',
      occurred_at: at,
      payload: {
        step_index: 0,
        step_id: 'wait-1',
        step_type: 'wait_element',
        ...extra
      }
    }) as any;

  const activity = (attempt: number, phase: string, at: string) =>
    stepEvent(`activity-${phase}-${attempt}`, `temporal.activity.${phase}`, at, {
      temporal_activity: true,
      activity_id: `exec-1.wait-1.attempt-${attempt}`,
      step_activity_id: `wait-1.attempt-${attempt}`,
      activity_attempt: attempt
    });

  const started = stepEvent('started', 'step.started', '2026-09-05T01:00:00.000Z');
  const completed = stepEvent(
    'completed',
    'step.completed',
    '2026-09-05T01:00:20.000Z',
    { message: 'wait_element ok' }
  );
  const batched = [
    activity(1, 'scheduled', '2026-09-05T01:00:01.000Z'),
    activity(1, 'failed', '2026-09-05T01:00:09.000Z'),
    activity(2, 'retrying', '2026-09-05T01:00:10.000Z'),
    activity(2, 'completed', '2026-09-05T01:00:19.000Z')
  ];

  const interleaved = foldEventsToStepLog([started, ...batched, completed]);
  const batchLate = foldEventsToStepLog([started, completed, ...batched]);

  assert.equal(interleaved.length, 1);
  assert.equal(batchLate.length, 1);
  assert.equal(interleaved[0].status, 'completed');
  assert.equal(batchLate[0].status, 'completed');
  assert.deepEqual(
    batchLate[0].temporal_activity_events?.map((event) => event.state),
    interleaved[0].temporal_activity_events?.map((event) => event.state)
  );
});

test('foldEventsToStepLog keeps each loop occurrence its own activity events when telemetry arrives late', () => {
  const at = (seconds: number) =>
    new Date(Date.UTC(2026, 8, 5, 1, 0, seconds)).toISOString();

  const stepEvents: any[] = [];
  const activityEvents: any[] = [];
  for (const iteration of [1, 2, 3]) {
    const base = iteration * 10;
    const payload = {
      step_index: 0,
      step_id: 'tap-in-loop',
      step_type: 'tap',
      depth: 1
    };
    stepEvents.push({
      event_id: `started-${iteration}`,
      event_type: 'step.started',
      execution_id: 'exec-1',
      step_id: 'tap-in-loop',
      occurred_at: at(base),
      payload
    });
    stepEvents.push({
      event_id: `completed-${iteration}`,
      event_type: 'step.completed',
      execution_id: 'exec-1',
      step_id: 'tap-in-loop',
      occurred_at: at(base + 3),
      payload
    });
    for (const [offset, phase] of [
      [1, 'scheduled'],
      [2, 'completed']
    ] as const) {
      activityEvents.push({
        event_id: `activity-${iteration}-${phase}`,
        event_type: `temporal.activity.${phase}`,
        execution_id: 'exec-1',
        step_id: 'tap-in-loop',
        occurred_at: at(base + offset),
        payload: {
          ...payload,
          temporal_activity: true,
          activity_id: `exec-1.tap-in-loop.iter-${iteration}`,
          activity_attempt: 1
        }
      });
    }
  }

  // Whole telemetry batch flushed at the end of the loop.
  const rows = foldEventsToStepLog([...stepEvents, ...activityEvents]);

  assert.equal(rows.length, 3);
  assert.deepEqual(
    rows.map((row) => row.temporal_activity_events?.length ?? 0),
    [2, 2, 2]
  );
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
