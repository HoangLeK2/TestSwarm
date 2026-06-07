import test from 'node:test';
import assert from 'node:assert/strict';
import { dlqDisplayMessage, dlqHasExplicitMessage } from './dlq-message.ts';

test('dlqDisplayMessage prefers display_message from API', () => {
  const msg = dlqDisplayMessage(
    {
      id: '1',
      execution_id: 'exec',
      device_serial: 'dev',
      retry_count: 0,
      status: 'pending',
      created_at: '',
      display_message: 'edge extra_data failed: no relay'
    },
    'fallback'
  );
  assert.equal(msg, 'edge extra_data failed: no relay');
});

test('dlqDisplayMessage prefers longer error over truncated failure_reason', () => {
  const msg = dlqDisplayMessage(
    {
      id: '1',
      execution_id: 'exec',
      device_serial: 'dev',
      retry_count: 0,
      status: 'pending',
      created_at: '',
      error:
        'edge extra_data failed: FK violation DETAIL: Key (campaign_id)=(abc) is not present',
      failure_reason: 'loop: iteration 0 failed'
    },
    'fallback'
  );
  assert.ok(msg.includes('FK violation'));
});

test('dlqDisplayMessage adds execution hints when fields empty', () => {
  const msg = dlqDisplayMessage(
    {
      id: '1',
      execution_id: 'exec-abc',
      device_serial: 'dev',
      retry_count: 0,
      status: 'pending',
      created_at: '',
      failed_step_id: 'extract-3'
    },
    'No error details'
  );
  assert.ok(msg.includes('failed_step_id=extract-3'));
  assert.ok(msg.includes('execution_id=exec-abc'));
});

test('dlqHasExplicitMessage is false for hint-only fallback', () => {
  assert.equal(
    dlqHasExplicitMessage({
      id: '1',
      execution_id: 'exec',
      device_serial: 'dev',
      retry_count: 0,
      status: 'pending',
      created_at: ''
    }),
    false
  );
});
