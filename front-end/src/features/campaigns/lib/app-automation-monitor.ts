import type { StepLogEntry } from '../types';

const APP_AUTOMATION_KEYS = [
  'app_popup_watchers',
  'locator_trace',
  'submit_trace',
  'form_fields',
  'assertions'
] as const;

export type AppAutomationMonitorDetails = {
  app_popup_watchers?: unknown[];
  locator_trace?: Record<string, unknown> | null;
  submit_trace?: Record<string, unknown> | null;
  form_fields?: Record<string, unknown> | null;
  assertions?: Record<string, unknown> | null;
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object'
    ? (value as Record<string, unknown>)
    : {};
}

export function pickAppAutomationDetails(
  source: Record<string, unknown>
): AppAutomationMonitorDetails | undefined {
  const details: AppAutomationMonitorDetails = {};
  let found = false;
  for (const key of APP_AUTOMATION_KEYS) {
    if (source[key] === undefined) continue;
    found = true;
    (details as Record<string, unknown>)[key] = source[key];
  }
  return found ? details : undefined;
}

export function mergeAppAutomationDetails(
  target: Record<string, unknown> | undefined,
  source: Record<string, unknown>
): Record<string, unknown> | undefined {
  const picked = pickAppAutomationDetails(source);
  if (!picked) return target;
  return {
    ...(target ?? {}),
    ...picked
  };
}

export function appAutomationDetailsFromLog(
  logEntry?: StepLogEntry
): AppAutomationMonitorDetails | null {
  if (!logEntry) return null;
  const root = record(logEntry);
  const details = record(logEntry.details);
  const merged = {
    ...pickAppAutomationDetails(root),
    ...pickAppAutomationDetails(details)
  };
  return Object.keys(merged).length > 0 ? merged : null;
}

export function shortTrace(
  trace: unknown,
  labels: { score?: string } = {}
): string {
  const item = record(trace);
  const locator = String(item.locator_name ?? '').trim();
  const reason = String(item.reason ?? '').trim();
  const fallback = String(item.fallback_level ?? '').trim();
  const score =
    typeof item.score === 'number'
      ? item.score.toFixed(2)
      : String(item.score ?? '').trim();
  return [
    locator,
    score ? `${labels.score ?? 'score'} ${score}` : '',
    fallback,
    reason
  ]
    .filter(Boolean)
    .join(' · ');
}

export function watcherLabel(watcher: unknown): string {
  const item = record(watcher);
  const name = String(item.name ?? '').trim();
  const message = String(item.message ?? '').trim();
  const reason = String(item.reason ?? '').trim();
  return [name, message, reason].filter(Boolean).join(' · ');
}
