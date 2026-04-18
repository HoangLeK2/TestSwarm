import type { FlowNode, FlowEdge } from './components/scenario-steps/types';
export type CampaignStatus = 'idle' | 'running' | 'draft' | 'paused' | 'completed';

/** Ready to start a new run (not executing, not user-paused mid-run) */
export function isIdleStatus(s: string): boolean {
  return s === 'idle' || s === 'draft' || s === 'completed';
}

/** Executing or user paused — poll workflows, show pause/resume/stop */
export function isCampaignActiveExecution(s: string): boolean {
  return s === 'running' || s === 'paused';
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
};

export type ScenarioUpdate = Partial<ScenarioCreate>;

export type CampaignOut = {
  id: string;
  name: string;
  description: string | null;
  status: CampaignStatus;
  user_id: string;
  scenario?: Record<string, any> | null;
  variables?: Record<string, any>;
  scenarios?: ScenarioOut[];
  created_at: string;
  updated_at: string;
  devices?: CampaignDeviceOut[];
  target_group_id?: string | null;
};

export type CampaignDeviceOut = {
  id: string;
  serial: string;
  name: string;
  brand?: string;
  model?: string;
};

export type CampaignCreate = {
  name: string;
  description?: string;
  scenario?: Record<string, any>;
  variables?: Record<string, any>;
  device_ids?: string[];
  target_group_id?: string | null;
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

export type WorkflowStatus = 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'PAUSED' | 'paused_on_error' | 'TERMINATED';

export type WorkflowInfo = {
  workflow_id: string;
  run_id: string;
  status: WorkflowStatus;
  start_time: string;
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
};

export type StepLogEntry = {
  index: number;
  step_type: string;
  ok: boolean;
  message: string | null;
  depth: number;
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

export type DlqStatus = 'pending' | 'retrying' | 'resolved' | 'failed' | 'dismissed' | 'unknown';

export type DlqEntry = {
  id: string;
  execution_id: string;
  device_serial: string;
  error: string | null;
  retry_count: number;
  status: DlqStatus;
  last_attempt_at: string | null;
  created_at: string;
};

export type ExecutionOut = {
  id: string;
  run_type: string;
  status: string;
  campaign_id: string | null;
  scenario_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

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
