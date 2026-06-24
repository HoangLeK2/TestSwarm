import type { RecoveryOutcome, RecoveryPolicy, RecoveryRule } from '../types';

export const RECOVERY_EDITOR_OUTCOMES: RecoveryOutcome[] = [
  'retry_step',
  'continue',
  'fail'
];

const DEFAULT_MAX_TOTAL_ATTEMPTS = 100;
const DEFAULT_MAX_ATTEMPTS_PER_STEP = 2;

type RecoveryRuleMatch = NonNullable<RecoveryRule['match']>;

function clampInt(value: unknown, fallback: number, min: number, max: number) {
  const parsed = Number(value);
  const next = Number.isFinite(parsed) ? Math.trunc(parsed) : fallback;
  return Math.max(min, Math.min(max, next));
}

function normalizeOutcome(value: unknown): RecoveryOutcome {
  return RECOVERY_EDITOR_OUTCOMES.includes(value as RecoveryOutcome)
    ? (value as RecoveryOutcome)
    : 'retry_step';
}

function stripStepScopedMatch(
  match: RecoveryRule['match']
): RecoveryRule['match'] {
  if (!match) return undefined;
  const {
    step_type_any: _stepTypeAny,
    strategy_any: _strategyAny,
    ...sharedMatch
  } = match as RecoveryRuleMatch;
  return Object.keys(sharedMatch).length ? sharedMatch : undefined;
}

export function normalizeRecoveryRuleForEditor(
  rule: RecoveryRule
): RecoveryRule {
  const normalizedOutcome = normalizeOutcome(rule.outcome ?? rule.on_success);
  return {
    ...rule,
    incident_type: rule.incident_type ?? rule.incident_types?.[0] ?? 'unknown',
    incident_types: rule.incident_types?.length
      ? rule.incident_types
      : [rule.incident_type ?? 'unknown'],
    scope: {},
    match: stripStepScopedMatch(rule.match),
    scenario_id: rule.scenario_id || null,
    scenario_name: rule.scenario_name || null,
    outcome: normalizedOutcome,
    on_success: normalizedOutcome,
    on_failure: rule.on_failure ?? 'fail',
    max_attempts: clampInt(rule.max_attempts, 1, 1, 10),
    timeout_ms: clampInt(rule.timeout_ms, 60_000, 5_000, 180_000)
  };
}

export function normalizeRecoveryPolicyForEditor(
  value?: RecoveryPolicy | null
): RecoveryPolicy {
  return {
    enabled: Boolean(value?.enabled),
    max_total_attempts: clampInt(
      value?.max_total_attempts,
      DEFAULT_MAX_TOTAL_ATTEMPTS,
      0,
      10_000
    ),
    max_attempts_per_step: clampInt(
      value?.max_attempts_per_step,
      DEFAULT_MAX_ATTEMPTS_PER_STEP,
      0,
      20
    ),
    rules: Array.isArray(value?.rules)
      ? value.rules.map(normalizeRecoveryRuleForEditor)
      : []
  };
}

export function createDefaultRecoveryRule(
  scenarioId: string | null
): RecoveryRule {
  return normalizeRecoveryRuleForEditor({
    incident_type: 'unknown',
    scope: {},
    scenario_id: scenarioId,
    outcome: 'retry_step',
    max_attempts: 1,
    timeout_ms: 60_000
  });
}
