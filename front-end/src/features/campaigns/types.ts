export type CampaignStatus = 'draft' | 'running' | 'paused' | 'completed';

export type ScenarioOut = {
  id: string;
  campaign_id: string;
  name: string;
  instructions: string;
  steps: Record<string, any>[];
  order: number;
  created_at: string;
  updated_at: string;
};

export type ScenarioCreate = {
  name?: string;
  instructions?: string;
  steps?: Record<string, any>[];
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
  scenarios?: ScenarioOut[];
  created_at: string;
  updated_at: string;
  devices?: CampaignDeviceOut[];
};

export type CampaignDeviceOut = {
  id: string;
  serial: string;
  name: string;
  brand?: string;
  model?: string;
};

export type CampaignCreate = { name: string; description?: string };

export type TaskOut = {
  id: string;
  name: string;
  status: string;
  target: string | null;
  result?: unknown;
  error?: string | null;
  finished_at: string | null;
};
