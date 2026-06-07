import type { CampaignDeviceOut } from '../../types';
import { deviceSelectFullTitle } from '@/features/devices/lib/device-select-label';

export type DlqHumanMessage = {
  /** Operator-facing summary (localized). */
  summary: string;
  /** Original / technical text for support & detail drawer. */
  technical: string;
};

type Translate = (
  key: string,
  values?: Record<string, string | number>
) => string;

const UNKNOWN_MSG_RE =
  /execution failed without a recorded error message/i;
const SERVER_RESTART_RE = /interrupted by server restart at step (\d+)/i;
const LOOP_RE = /^loop:\s*iteration\s+(\d+)\s+failed\s*[—–-]\s*(.+)$/i;
const RUN_SCENARIO_PREFIX_RE =
  /^run_scenario:\s*sub-scenario\s+'[^']+'\s+failed\s*[—–-]\s*/i;

function normalizeRaw(raw: string): string {
  return raw.replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
}

function stripRunScenarioPrefix(text: string): string {
  return text.replace(RUN_SCENARIO_PREFIX_RE, '').trim();
}

function humanizeCore(text: string, t: Translate): string | null {
  const msg = normalizeRaw(text);
  if (!msg) return null;

  if (UNKNOWN_MSG_RE.test(msg) || msg.includes('execution_id=')) {
    return t('monitorDlqErrUnknown');
  }

  const restart = msg.match(SERVER_RESTART_RE);
  if (restart) {
    return t('monitorDlqErrServerRestart', { step: restart[1] });
  }

  if (/no relay for device/i.test(msg)) {
    return t('monitorDlqErrNoRelay');
  }

  if (/grpc agent disconnected/i.test(msg)) {
    return t('monitorDlqErrRelayDisconnected');
  }

  if (/edge extra_data failed:\s*extra_data_failed/i.test(msg)) {
    return t('monitorDlqErrExtraDataFailed');
  }

  if (/tap_fb_comment_button:\s*then branch failed/i.test(msg)) {
    return t('monitorDlqErrCommentTapFailed');
  }

  const selector = msg.match(
    /selector text='([^']+)'\s+not found(?:,\s*no fallback position)?/i
  );
  if (selector) {
    return t('monitorDlqErrSelectorNotFound', {
      selector: normalizeRaw(selector[1])
    });
  }

  if (/edge extra_data fb_posts:/i.test(msg) && /failed/i.test(msg)) {
    return t('monitorDlqErrPostExtractFailed');
  }

  if (/launch_app\([^)]+\)\s+failed/i.test(msg)) {
    return t('monitorDlqErrLaunchAppFailed');
  }

  if (/cancelled/i.test(msg)) {
    return t('monitorDlqErrCancelled');
  }

  return null;
}

/** Turn raw DLQ/engine text into a short operator-friendly message. */
export function humanizeDlqMessage(raw: string, t: Translate): DlqHumanMessage {
  const technical = normalizeRaw(raw);
  if (!technical) {
    return { summary: t('monitorDlqNoErrorMessage'), technical: '' };
  }

  const withoutScenario = stripRunScenarioPrefix(technical);
  const loop = withoutScenario.match(LOOP_RE);
  if (loop) {
    const inner = humanizeCore(loop[2], t) ?? loop[2];
    return {
      summary: t('monitorDlqErrLoopIteration', {
        iteration: loop[1],
        detail: inner
      }),
      technical
    };
  }

  const direct = humanizeCore(withoutScenario, t);
  if (direct) {
    return { summary: direct, technical };
  }

  // Last resort: drop UUID-ish noise but keep readable tail.
  const simplified = withoutScenario
    .replace(/sub-scenario\s+'[0-9a-f-]{36}'/gi, t('monitorDlqErrSubScenario'))
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, '')
    .replace(/\s{2,}/g, ' ')
    .trim();

  return {
    summary: simplified.length > 0 ? simplified : t('monitorDlqErrUnknown'),
    technical
  };
}

export function resolveDlqDeviceLabel(
  serial: string,
  devices: CampaignDeviceOut[] | undefined,
  t: Translate
): { label: string; title: string } {
  const trimmed = serial.trim();
  if (!trimmed) {
    return {
      label: t('monitorDlqDeviceUnknown'),
      title: t('monitorDlqDeviceUnknownHint')
    };
  }

  const device = devices?.find((d) => d.serial === trimmed);
  if (device) {
    const name = device.name?.trim();
    const model = `${device.brand ?? ''} ${device.model ?? ''}`.trim();
    const label = name || model || trimmed;
    return {
      label,
      title: deviceSelectFullTitle({
        brand: device.brand ?? '',
        model: device.model ?? '',
        serial: device.serial
      })
    };
  }

  return { label: trimmed, title: trimmed };
}
