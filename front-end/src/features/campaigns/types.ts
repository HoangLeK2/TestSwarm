import type { FlowNode, FlowEdge } from './components/scenario-steps/types';

/** Epic 04 lifecycle + legacy statuses from backend FSM (DF-T-04-007). */
export type CampaignStatus =
  | 'draft'
  | 'scheduled'
  | 'idle'
  | 'running'
  | 'paused'
  | 'completed'
  | 'cancelled'
  | 'failed'
  | 'archived';

const DISPATCHABLE = new Set<string>([
  'draft',
  'idle',
  'scheduled',
  'cancelled',
  'completed',
  'failed'
]);
const ACTIVE_EXECUTION = new Set<string>(['running', 'paused']);
const BODY_EDITABLE = new Set<string>([
  'draft',
  'idle',
  'cancelled',
  'completed',
  'failed'
]);
const TERMINAL = new Set<string>(['completed', 'failed', 'archived']);

/** Campaign may start a new run / dispatch (draft, scheduled, legacy idle). */
export function isDispatchableStatus(s: string): boolean {
  return DISPATCHABLE.has(s);
}

/** Campaign has an active execution (running or paused). */
export function isActiveExecutionStatus(s: string): boolean {
  return ACTIVE_EXECUTION.has(s);
}

/** @deprecated Use isDispatchableStatus */
export function isIdleStatus(s: string): boolean {
  return isDispatchableStatus(s);
}

/** Executing or user paused — poll workflows, show pause/resume/cancel. */
export function isCampaignActiveExecution(s: string): boolean {
  return ACTIVE_EXECUTION.has(s);
}

/** Metadata (name, description, tags) editable in scheduled. */
export function isCampaignMetadataEditable(s: string): boolean {
  return BODY_EDITABLE.has(s) || s === 'scheduled';
}

/** Body fields (scenario_refs, vars, overrides) editable before (re-)dispatch. */
export function isCampaignBodyEditable(s: string): boolean {
  return BODY_EDITABLE.has(s);
}

/** Terminal lifecycle — hide run, no active control except archive/delete where allowed. */
export function isCampaignTerminal(s: string): boolean {
  return TERMINAL.has(s);
}

export type ScenarioOut = {
  id: string;
  campaign_id: string;
  name: string;
  instructions: string;
  steps: Record<string, any>[];
  variables: Record<string, any>;
  order: number;
  nodes: FlowNode[];
  edges: FlowEdge[];
  account_group_id?: string | null;
  account_group_name?: string | null;
  created_at: string;
  updated_at: string;
};

export type ScenarioCreate = {
  name?: string;
  instructions?: string;
  steps?: Record<string, any>[];
  variables?: Record<string, any>;
  order?: number;
  nodes?: FlowNode[];
  edges?: FlowEdge[];
  /** Empty string clears the binding. */
  account_group_id?: string | null;
};

export type ScenarioUpdate = Partial<ScenarioCreate>;

export type CampaignScenarioRefOut = {
  scenario_id: string;
  scenario_version: number;
  repeat_count: number;
};

export type RecoveryIncidentType =
  | 'app_popup'
  | 'facebook_popup'
  | 'profile_page'
  | 'lost_post_detail'
  | 'comment_panel_closed'
  | 'stuck_screen'
  | 'login_or_checkpoint'
  | 'unknown';

export type RecoveryOutcome =
  | 'retry_step'
  | 'continue'
  | 'fail'
  | 'pause_for_takeover'
  | 'open_dlq';

export type RecoveryRule = {
  incident_type?: RecoveryIncidentType;
  incident_types?: RecoveryIncidentType[];
  scope?: {
    step_type_any?: string[];
    step_id_any?: string[];
    strategy_any?: string[];
    step_index_any?: number[];
  };
  scenario_id?: string | null;
  scenario_name?: string | null;
  outcome?: RecoveryOutcome;
  on_success?: RecoveryOutcome;
  on_failure?: RecoveryOutcome;
  match?: {
    text_any?: string[];
    text_all?: string[];
    result_any?: string[];
    package_any?: string[];
    activity_any?: string[];
    step_type_any?: string[];
    strategy_any?: string[];
    min_confidence?: number;
  };
  max_attempts?: number;
  timeout_ms?: number;
  success_check?: {
    require_post_detail?: boolean;
    require_comment_panel?: boolean;
  };
  success_checks?: Array<{
    type?: string;
    incident_type?: RecoveryIncidentType | string | null;
  }>;
};

export type RecoveryPolicy = {
  enabled?: boolean;
  max_total_attempts?: number;
  max_attempts_per_step?: number;
  rules?: RecoveryRule[];
};

export type CampaignOut = {
  id: string;
  name: string;
  description: string | null;
  status: CampaignStatus;
  user_id?: string | null;
  scenario?: Record<string, any> | null;
  variables?: Record<string, any>;
  scenarios?: ScenarioOut[];
  created_at: string;
  updated_at: string;
  devices?: CampaignDeviceOut[];
  target_group_id?: string | null;
  /** Epic 04 org-scoped campaign (present on list/detail when tenant has org). */
  organization_id?: string;
  scenario_refs?: CampaignScenarioRefOut[];
  vars?: Record<string, unknown>;
  tags?: string[];
  /** Epic 04 per-device variable overrides keyed by device_id. */
  per_device_overrides?: Record<string, Record<string, unknown>>;
  /** Campaign-level incident recovery, not part of the scenario node graph. */
  recovery_policy?: RecoveryPolicy;
};

export type CampaignDeviceOut = {
  id: string;
  serial: string;
  name: string;
  brand?: string;
  model?: string;
};

export type CampaignScenarioRefIn = {
  scenario_id: string;
  scenario_version?: number | null;
  repeat_count?: number | null;
};

export const CAMPAIGN_SCENARIO_REPEAT_MIN = 1;
export const CAMPAIGN_SCENARIO_REPEAT_MAX = 20;

export function normalizeCampaignScenarioRepeatCount(value: unknown): number {
  const parsed =
    typeof value === 'number'
      ? value
      : typeof value === 'string' && value.trim()
        ? Number(value)
        : CAMPAIGN_SCENARIO_REPEAT_MIN;
  if (!Number.isFinite(parsed)) return CAMPAIGN_SCENARIO_REPEAT_MIN;
  return Math.min(
    CAMPAIGN_SCENARIO_REPEAT_MAX,
    Math.max(CAMPAIGN_SCENARIO_REPEAT_MIN, Math.trunc(parsed))
  );
}

export function normalizeCampaignScenarioRefs(
  refs: CampaignScenarioRefIn[] | undefined | null
): CampaignScenarioRefIn[] {
  return (refs ?? [])
    .filter((ref) => ref.scenario_id)
    .map((ref) => ({
      scenario_id: ref.scenario_id,
      ...(ref.scenario_version != null
        ? { scenario_version: ref.scenario_version }
        : {}),
      repeat_count: normalizeCampaignScenarioRepeatCount(ref.repeat_count)
    }));
}

export function scenarioRefRunCount(
  refs: Array<Pick<CampaignScenarioRefIn, 'repeat_count'>>
): number {
  return refs.reduce(
    (sum, ref) => sum + normalizeCampaignScenarioRepeatCount(ref.repeat_count),
    0
  );
}

export type CampaignCreate = {
  name: string;
  description?: string;
  scenario?: Record<string, any>;
  variables?: Record<string, any>;
  vars?: Record<string, any>;
  tags?: string[];
  scenario_refs?: CampaignScenarioRefIn[];
  account_group_id?: string | null;
  scenario_account_id?: string | null;
  per_device_accounts?: Record<string, string>;
  device_ids?: string[];
  target_group_id?: string | null;
  recovery_policy?: RecoveryPolicy;
};

export type TaskOut = {
  id: string;
  name: string;
  status: string;
  target: string | null;
  result?: unknown;
  error?: string | null;
  finished_at: string | null;
};

// ── Temporal Workflow types ──────────────────────────────────────────────────

export type WorkflowStatus =
  | 'RUNNING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'
  | 'PAUSED'
  | 'paused_on_error'
  | 'TERMINATED';

export type WorkflowInfo = {
  workflow_id: string;
  run_id?: string | null;
  status: WorkflowStatus;
  start_time?: string | null;
  execution_id?: string | null;
  campaign_id?: string | null;
  campaign_name?: string | null;
  scenario_id?: string | null;
  scenario_name?: string | null;
  scenario_steps?: Record<string, any>[] | null;
  scenario_count?: number | null;
  device_serial?: string | null;
  workflow_kind?: 'main' | 'recovery' | string | null;
  dispatch_source?: string | null;
};

export type CampaignWorkflowsResponse = {
  campaign_id: string;
  workflows: WorkflowInfo[];
  execution_engine?: 'temporal' | 'task_queue';
  temporal_available?: boolean;
};

export type WorkflowProgress = {
  workflow_id: string;
  status: string;
  current_step: number;
  total_steps: number;
  current_step_type: string;
  loop_iteration: number | null;
  message: string;
  device_serial: string;
  error_message?: string | null;
  current_step_started_at?: string | null;
  current_step_elapsed_ms?: number;
  running_step?: boolean;
};

export type StepLogEntry = {
  index: number;
  occurrence_key?: string;
  step_id?: string | null;
  type?: string;
  step_type: string;
  ok: boolean;
  message: string | null;
  depth: number;
  status?: 'running' | 'completed' | 'failed';
  output?: string | null;
  exit_code?: number | null;
  save_as?: string | null;
  output_truncated?: boolean;
  details?: Record<string, unknown>;
  incidents?: IncidentEvent[];
};

export type IncidentEvent = {
  event_type: string;
  incident_type?: RecoveryIncidentType | string;
  outcome?: RecoveryOutcome | string;
  message?: string | null;
  attempt?: number | null;
  scenario_id?: string | null;
  recovery_scenario_id?: string | null;
  recovery_scenario_name?: string | null;
  incident_key?: string | null;
  rule_id?: string | null;
  matched_rule?: boolean;
  confidence?: number | null;
};

export type WorkflowStepLog = {
  workflow_id: string;
  status: string;
  source: string;
  steps_count: number;
  steps: StepLogEntry[];
};

export type CampaignExecutionEngine = 'temporal' | 'task_queue';

export type CampaignRunResponse = {
  id: string;
  status: string;
  device_serials: string[];
  /** Present when execution_engine is temporal */
  workflow_ids?: string[];
  scenarios_count: number;
  /** Preferred: which runtime handled this run */
  execution_engine?: CampaignExecutionEngine;
  /** Alias of execution_engine (legacy) */
  engine?: CampaignExecutionEngine;
  /** True when Temporal was enabled but connection/start failed and TaskQueue was used */
  temporal_fallback?: boolean;
  temporal_fallback_reason?: string;
  /** Present when execution_engine is task_queue */
  task_ids?: string[];
};

export type DlqStatus =
  | 'pending'
  | 'retrying'
  | 'resolved'
  | 'replayed'
  | 'closed'
  | 'failed'
  | 'dismissed'
  | 'unknown';

export type DlqEntry = {
  id: string;
  execution_id: string;
  device_serial: string;
  error: string | null;
  retry_count: number;
  status: DlqStatus;
  last_attempt_at: string | null;
  created_at: string;
  campaign_id?: string | null;
  failed_step_id?: string | null;
  failure_reason?: string | null;
  failed_at?: string | null;
  closed_by?: string | null;
  closed_at?: string | null;
  close_reason?: string | null;
  replayed_to_execution_id?: string | null;
  artifact_refs?: Record<string, string>;
  /** Server-resolved message (includes execution_steps backfill). */
  display_message?: string;
};

export type DlqBulkRetryResult = {
  dlq_id?: string | null;
  execution_id?: string | null;
  status: string;
  reason?: string | null;
  message?: string | null;
  replayed_to_execution_id?: string | null;
  entry_status?: string | null;
};

export type DlqSummary = {
  pending_count: number;
  alert_threshold: number;
  alert: boolean;
  dismissed_offline_count: number;
  offline_dismiss_minutes: number;
};

export type ExecutionOut = {
  id: string;
  run_type: string;
  status: string;
  campaign_id: string | null;
  scenario_id: string | null;
  account_id?: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  device_config?: Record<string, unknown>;
  meta?: Record<string, unknown>;
};

export type { ExecutionEventOut } from '../device-farm/services/generated/DeviceFarmApi';

export type ExecutionArtifact = {
  artifact_type: string;
  execution_id: string;
  device_serial: string | null;
  step_index: number | null;
  step_type: string | null;
  ok: boolean | null;
  message: string | null;
  url: string | null;
  metadata: Record<string, any>;
  created_at: string | null;
};
