/**
 * Operator-facing text for `platform_session_gate` step messages.
 *
 * The engine writes machine reasons (`platform_session_gate preflight blocked:
 * checkpoint_visible`) into the step message so the log stays greppable. Those
 * strings tell an operator nothing, so every surface that renders a step
 * message runs it through here first. Keys live in the `executionMessages`
 * namespace so activity feed, run history and DLQ can share one wording.
 */

type Translate = (
  key: string,
  values?: Record<string, string | number>
) => string;

const BLOCKED_RE =
  /platform_session_gate\s+(preflight|confirm)\s+blocked:\s*([a-z0-9_]+)/i;
const OUTCOME_RE =
  /platform_session_gate\s+(?:preflight|confirm):\s*(ready|login required)/i;
const UNSUPPORTED_RE =
  /platform_session_gate:\s*platform\s*'([^']*)'\s*does not implement/i;
const FAILED_RE = /platform_session_gate\s+failed:\s*(.+)$/i;

/** Blocking reasons the gate can emit: readiness reasons plus gate verdicts. */
const REASON_KEY: Record<string, string> = {
  checkpoint_visible: 'sessionGateCheckpoint',
  login_surface_visible: 'sessionGateLoggedOut',
  app_unresponsive: 'sessionGateAppUnresponsive',
  hierarchy_unavailable: 'sessionGateScreenUnreadable',
  invalid_hierarchy: 'sessionGateScreenUnreadable',
  readiness_markers_not_found: 'sessionGateScreenUnknown',
  platform_readiness_not_implemented: 'sessionGateUnsupportedPlatform'
};

const REASON_SUFFIX_KEY: Record<string, string> = {
  _package_not_visible: 'sessionGateAppNotVisible',
  _session_account_mismatch: 'sessionGateAccountMismatch',
  _ready_without_matching_provenance: 'sessionGateUntrustedSession',
  _login_provenance_missing: 'sessionGateLoginNotConfirmed'
};

/** Exceptions raised while resolving the run's org / device / account. */
const FAILURE_PATTERNS: [RegExp, string][] = [
  [/requires an execution account/i, 'sessionGateNoRunAccount'],
  [/requires account_id or execution_id/i, 'sessionGateNoRunAccount'],
  [/account conflicts with execution account/i, 'sessionGateAccountConflict'],
  [/account was not found/i, 'sessionGateAccountNotFound'],
  [/device is not part of the execution/i, 'sessionGateDeviceNotInRun'],
  [
    /device was not found in the account organization/i,
    'sessionGateDeviceNotInOrg'
  ]
];

function normalize(raw: string): string {
  return raw
    .replace(/\u00a0/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Localized text for a session-gate message, or `null` when the message is not
 * one — callers keep their own fallback for everything else.
 */
export function humanizeSessionGateMessage(
  raw: string | null | undefined,
  t: Translate
): string | null {
  const message = normalize(raw ?? '');
  if (!message || !/platform_session_gate/i.test(message)) return null;

  const blocked = message.match(BLOCKED_RE);
  if (blocked) {
    const reason = blocked[2].toLowerCase();
    const suffixKey = Object.entries(REASON_SUFFIX_KEY).find(([suffix]) =>
      reason.endsWith(suffix)
    )?.[1];
    const key = REASON_KEY[reason] ?? suffixKey;
    return key ? t(key) : t('sessionGateBlockedOther', { reason: blocked[2] });
  }

  const unsupported = message.match(UNSUPPORTED_RE);
  if (unsupported) {
    return t('sessionGateUnsupportedPlatform');
  }

  const failed = message.match(FAILED_RE);
  if (failed) {
    const detail = normalize(failed[1]);
    const matched = FAILURE_PATTERNS.find(([pattern]) => pattern.test(detail));
    return matched ? t(matched[1]) : t('sessionGateFailed', { detail });
  }

  const outcome = message.match(OUTCOME_RE);
  if (outcome) {
    return outcome[1].toLowerCase() === 'ready'
      ? t('sessionGateReady')
      : t('sessionGateLoginRequired');
  }

  return null;
}
