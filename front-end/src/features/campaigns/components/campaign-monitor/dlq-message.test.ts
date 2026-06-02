import test from 'node:test';
import assert from 'node:assert/strict';
import { dlqDisplayMessage } from './dlq-message.ts';

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

test('dlqDisplayMessage falls back when both fields empty', () => {
  assert.equal(
    dlqDisplayMessage(
      {
        id: '1',
        execution_id: 'exec',
        device_serial: 'dev',
        retry_count: 0,
        status: 'pending',
        created_at: ''
      },
      'No error details'
    ),
    'No error details'
  );
});
