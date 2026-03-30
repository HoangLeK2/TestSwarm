export type CampaignStatus = 'draft' | 'running' | 'paused' | 'completed';

export type ScenarioOut = {
  id: string;
  campaign_id: string;
  name: string;
  instructions: string;
  steps: Record<string, any>[];
  variables: Record<string, any>;
  order: number;
  created_at: string;
  updated_at: string;
};

export type ScenarioCreate = {
  name?: string;
  instructions?: string;
  steps?: Record<string, any>[];
  variables?: Record<string, any>;
  order?: number;
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

export type WorkflowStatus = 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'PAUSED' | 'TERMINATED';

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
