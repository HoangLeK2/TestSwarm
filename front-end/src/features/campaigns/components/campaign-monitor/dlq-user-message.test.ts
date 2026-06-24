import test from 'node:test';
import assert from 'node:assert/strict';
import { humanizeDlqMessage } from './dlq-user-message.ts';

const t = (key: string, values?: Record<string, string | number>) => {
  const map: Record<string, string> = {
    monitorDlqErrUnknown: 'Lỗi không rõ — thử chạy lại',
    monitorDlqErrNoRelay: 'Relay chưa kết nối',
    monitorDlqErrLoopIteration: `Vòng ${values?.iteration}: ${values?.detail}`,
    monitorDlqErrExtraDataFailed:
      'Thu thập dữ liệu bài viết thất bại trên thiết bị.',
    monitorDlqErrSelectorNotFound: `Không thấy "${values?.selector}"`,
    monitorDlqNoErrorMessage: 'Không có mô tả'
  };
  return map[key] ?? key;
};

test('humanizeDlqMessage hides u2 stack trace from technical detail', () => {
  const raw =
    'loop: iteration 1 failed — edge extra_data failed: [server] INFO: [UiAutomator2Server] java.lang.IllegalStateException: UiAutomationService already registered!';
  const out = humanizeDlqMessage(raw, t);
  assert.ok(!out.technical.includes('IllegalStateException'));
  assert.equal(out.technical, out.summary);
});

test('humanizeDlqMessage maps u2 transient extra_data inside loop', () => {
  const out = humanizeDlqMessage(
    'loop: iteration 1 failed — edge extra_data failed: [server] INFO: [UiAutomator2Server] Starting Server java.lang.IllegalStateException: UiAutomationService already registered!',
    t
  );
  assert.ok(out.summary.includes('Vòng 1'));
  assert.ok(out.summary.includes('Thu thập dữ liệu'));
  assert.ok(!out.summary.includes('IllegalStateException'));
});

test('humanizeDlqMessage maps no relay inside loop', () => {
  const out = humanizeDlqMessage(
    "run_scenario: sub-scenario 'b5752658-9cef-42cb-bb03-e7f82de05c92' failed — loop: iteration 44 failed — edge extra_data fb_posts: no relay for device (start agent-boot relay and ensure device is registered)",
    t
  );
  assert.ok(out.summary.includes('Vòng 44'));
  assert.ok(out.summary.includes('Relay chưa kết nối'));
});

test('humanizeDlqMessage maps unknown fallback', () => {
  const out = humanizeDlqMessage(
    'Execution failed without a recorded error message (inspect execution_steps, worker logs, or Temporal history) (execution_id=abc)',
    t
  );
  assert.equal(out.summary, 'Lỗi không rõ — thử chạy lại');
});

test('humanizeDlqMessage maps selector not found', () => {
  const out = humanizeDlqMessage(
    "selector text='OpenClaw VN · Truy cập' not found, no fallback position",
    t
  );
  assert.ok(out.summary.includes('OpenClaw VN'));
});
