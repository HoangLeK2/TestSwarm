export type ContinuousCrawlStatus =
  | 'idle'
  | 'preflight'
  | 'starting'
  | 'running'
  | 'pausing'
  | 'paused'
  | 'cancelling'
  | 'cancelled'
  | 'completed'
  | 'failed';

export type ContinuousCrawlHealth = 'healthy' | 'degraded' | 'critical';
export type ContinuousCrawlLaneStatus =
  | 'idle'
  | 'running'
  | 'paused'
  | 'offline'
  | 'failed';

export type ContinuousCrawlDeviceLane = {
  device_serial: string;
  status: ContinuousCrawlLaneStatus;
  target_id?: string | null;
  target_label?: string | null;
  completed: number;
  failed: number;
  message?: string | null;
};

export type ContinuousCrawlTargetSummary = {
  target_id: string;
  label?: string | null;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  device_serial?: string | null;
  message?: string | null;
};

export type ContinuousCrawlProgress = {
  campaign_id: string;
  dispatch_id?: string | null;
  status: ContinuousCrawlStatus;
  health: ContinuousCrawlHealth;
  loaded: number;
  active: number;
  succeeded: number;
  failed: number;
  consecutive_failures: number;
  exhausted: boolean;
  generation: number;
  max_targets?: number | null;
  message?: string | null;
  updated_at?: string | null;
  device_lanes: ContinuousCrawlDeviceLane[];
  recent_targets: ContinuousCrawlTargetSummary[];
};

export type ContinuousCrawlPreflight = {
  ready: boolean;
  target_count?: number | null;
  device_count: number;
  max_concurrency: number;
  device_targets: Array<{
    device_id: string;
    device_serial: string;
    device_name: string;
    target_count: number;
  }>;
  warnings: string[];
  errors: string[];
};

export type ContinuousCrawlStartResponse = {
  campaign_id: string;
  dispatch_id: string;
  workflow_id: string;
  status: ContinuousCrawlStatus;
};

export type ContinuousCrawlControl = 'pause' | 'resume' | 'cancel';

export const MAX_RENDERED_CRAWL_LANES = 12;
export const MAX_RENDERED_CRAWL_TARGETS = 8;
const RESERVED_CAMPAIGN_VARIABLES = new Set([
  '_crawl',
  '_continuous_crawl',
  '__CAPTURE_MODE__'
]);

export const CAPTURE_MODES = ['error_only', 'extract_only', 'all'] as const;
export type CaptureMode = (typeof CAPTURE_MODES)[number];

export function readCaptureMode(variables: unknown): CaptureMode {
  const raw =
    variables && typeof variables === 'object'
      ? (variables as Record<string, unknown>).__CAPTURE_MODE__
      : null;
  const mode = String(raw ?? '')
    .trim()
    .toLowerCase();
  return (CAPTURE_MODES as readonly string[]).includes(mode)
    ? (mode as CaptureMode)
    : 'error_only';
}

export function writeCaptureMode(
  variables: Record<string, unknown>,
  mode: CaptureMode
): Record<string, unknown> {
  return { ...variables, __CAPTURE_MODE__: mode };
}

export type ContinuousCrawlSettings = {
  enabled: boolean;
};

export function readContinuousCrawlSettings(
  variables: unknown
): ContinuousCrawlSettings {
  const crawl =
    variables && typeof variables === 'object'
      ? (variables as Record<string, unknown>)._crawl
      : null;
  const config =
    crawl && typeof crawl === 'object'
      ? (crawl as Record<string, unknown>)
      : {};
  return {
    enabled: config.mode === 'continuous_source_pool'
  };
}

export function updateContinuousCrawlSettings(
  variables: Record<string, unknown>,
  settings: ContinuousCrawlSettings
): Record<string, unknown> {
  const existing = variables._crawl;
  const existingCrawl =
    existing && typeof existing === 'object'
      ? (existing as Record<string, unknown>)
      : {};
  const crawl = Object.fromEntries(
    Object.entries(existingCrawl).filter(
      ([key]) => key !== 'max_concurrency' && key !== 'max_targets'
    )
  );
  return {
    ...variables,
    _crawl: {
      ...crawl,
      mode: settings.enabled ? 'continuous_source_pool' : 'fixed_fan_out'
    }
  };
}

export function campaignVariablesForEditor(
  variables: Record<string, unknown>
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(variables).filter(
      ([key]) => !RESERVED_CAMPAIGN_VARIABLES.has(key)
    )
  );
}

export function mergeCampaignEditorVariables(
  current: Record<string, unknown>,
  editable: Record<string, unknown>
): Record<string, unknown> {
  const reserved = Object.fromEntries(
    Object.entries(current).filter(([key]) =>
      RESERVED_CAMPAIGN_VARIABLES.has(key)
    )
  );
  return { ...reserved, ...editable };
}

export function isContinuousCrawl(variables: unknown): boolean {
  if (!variables || typeof variables !== 'object') return false;
  const crawl = (variables as Record<string, unknown>)._crawl;
  return (
    !!crawl &&
    typeof crawl === 'object' &&
    (crawl as Record<string, unknown>).mode === 'continuous_source_pool'
  );
}

export function crawlCompletion(progress: ContinuousCrawlProgress): {
  completed: number;
  percent: number | null;
} {
  const completed = progress.succeeded + progress.failed;
  const total = progress.exhausted
    ? Math.max(progress.loaded, completed)
    : progress.max_targets;
  return {
    completed,
    percent: total ? Math.min(100, Math.round((completed / total) * 100)) : null
  };
}

export function reduceContinuousCrawlProgress(
  current: ContinuousCrawlProgress | undefined,
  incoming: ContinuousCrawlProgress
): ContinuousCrawlProgress {
  if (!current || current.dispatch_id !== incoming.dispatch_id) return incoming;
  if (incoming.generation < current.generation) return current;
  const currentTime = current.updated_at ? Date.parse(current.updated_at) : 0;
  const incomingTime = incoming.updated_at
    ? Date.parse(incoming.updated_at)
    : 0;
  if (
    incoming.generation === current.generation &&
    currentTime > 0 &&
    incomingTime > 0 &&
    incomingTime < currentTime
  ) {
    return current;
  }
  return incoming;
}

export function boundedCrawlRows(progress: ContinuousCrawlProgress) {
  return {
    lanes: progress.device_lanes.slice(0, MAX_RENDERED_CRAWL_LANES),
    targets: progress.recent_targets.slice(0, MAX_RENDERED_CRAWL_TARGETS)
  };
}

export function continuousCrawlPollInterval(
  status: ContinuousCrawlStatus | undefined
): number | false {
  return status &&
    ['running', 'starting', 'pausing', 'paused', 'cancelling'].includes(status)
    ? 5_000
    : false;
}
