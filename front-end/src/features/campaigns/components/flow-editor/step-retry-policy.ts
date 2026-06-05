import type { FlowStep } from '../scenario-steps/types';

export type RetryBackoffStrategy = 'fixed' | 'exponential';

export type StepRetryPolicy = {
  max_attempts: number;
  backoff_ms: number;
  backoff_strategy: RetryBackoffStrategy;
  jitter: number;
  backoff_cap_ms?: number;
  retryable_reasons?: string[];
};

export const DEFAULT_STEP_RETRY_POLICY: StepRetryPolicy = {
  max_attempts: 3,
  backoff_ms: 1000,
  backoff_strategy: 'exponential',
  jitter: 0.2
};

const MAX_ATTEMPTS = 10;
const MAX_BACKOFF_MS = 60_000;

function clampNumber(
  value: unknown,
  fallback: number,
  min: number,
  max: number
) {
  const n =
    typeof value === 'number'
      ? value
      : typeof value === 'string' && value.trim()
        ? Number(value)
        : NaN;
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

export function parseRetryReasons(raw: string): string[] {
  const seen = new Set<string>();
  for (const part of raw.split(/[,\n]/)) {
    const reason = part.trim();
    if (reason) seen.add(reason);
  }
  return Array.from(seen);
}

export function formatRetryReasons(raw: unknown): string {
  if (!raw || typeof raw !== 'object') return '';
  const policy = raw as {
    retryable_reasons?: unknown;
    on?: unknown;
  };
  const reasons = Array.isArray(policy.retryable_reasons)
    ? policy.retryable_reasons
    : Array.isArray(policy.on)
      ? policy.on
      : [];
  return reasons.filter(Boolean).map(String).join(', ');
}

export function coerceStepRetryPolicy(raw: unknown): StepRetryPolicy {
  const policy =
    raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const strategy =
    String(
      policy.backoff_strategy ?? DEFAULT_STEP_RETRY_POLICY.backoff_strategy
    ) === 'fixed'
      ? 'fixed'
      : 'exponential';

  const retryableReasons = Array.isArray(policy.retryable_reasons)
    ? policy.retryable_reasons.filter(Boolean).map(String)
    : Array.isArray(policy.on)
      ? policy.on.filter(Boolean).map(String)
      : undefined;

  const next: StepRetryPolicy = {
    max_attempts: Math.round(
      clampNumber(
        policy.max_attempts ?? policy.attempts,
        DEFAULT_STEP_RETRY_POLICY.max_attempts,
        2,
        MAX_ATTEMPTS
      )
    ),
    backoff_ms: Math.round(
      clampNumber(
        policy.backoff_ms,
        DEFAULT_STEP_RETRY_POLICY.backoff_ms,
        0,
        MAX_BACKOFF_MS
      )
    ),
    backoff_strategy: strategy,
    jitter: clampNumber(policy.jitter, DEFAULT_STEP_RETRY_POLICY.jitter, 0, 1)
  };

  if (policy.backoff_cap_ms != null) {
    next.backoff_cap_ms = Math.round(
      clampNumber(policy.backoff_cap_ms, MAX_BACKOFF_MS, 0, MAX_BACKOFF_MS)
    );
  }
  if (retryableReasons?.length) {
    next.retryable_reasons = retryableReasons;
  }

  return next;
}

export function withRetryField(
  retry: unknown,
  key: keyof StepRetryPolicy,
  value: StepRetryPolicy[keyof StepRetryPolicy]
): StepRetryPolicy {
  const next = {
    ...coerceStepRetryPolicy(retry),
    [key]: value
  };
  if (
    key === 'retryable_reasons' &&
    Array.isArray(value) &&
    value.length === 0
  ) {
    delete next.retryable_reasons;
  }
  return coerceStepRetryPolicy(next);
}

export function retryPatchForEnabledState(
  step: FlowStep,
  enabled: boolean
): Partial<FlowStep> {
  if (!enabled) return { retry: undefined };
  return { retry: coerceStepRetryPolicy(step.retry) };
}
