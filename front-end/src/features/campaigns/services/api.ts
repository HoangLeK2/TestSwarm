import { farmApi } from '@/lib/farm-api';
import type {
  CampaignCreate,
  CampaignDeviceOut,
  CampaignOut,
  CampaignRunResponse,
  CampaignStatus,
  CampaignWorkflowsResponse,
  ScenarioCreate,
  ScenarioOut,
  ScenarioUpdate,
  TaskOut,
  WorkflowProgress
} from '../types';

export type {
  CampaignCreate,
  CampaignDeviceOut,
  CampaignOut,
  CampaignRunResponse,
  CampaignStatus,
  CampaignWorkflowsResponse,
  ScenarioCreate,
  ScenarioOut,
  ScenarioUpdate,
  TaskOut,
  WorkflowProgress
} from '../types';

export type StepActionResponse = {
  action: string;
  signalled: string[];
  errors: string[];
  total: number;
};

export const campaignsApi = {
  list: () => farmApi.get<CampaignOut[]>('/campaigns').then((r) => r.data),
  create: (data: CampaignCreate) =>
    farmApi.post<CampaignOut>('/campaigns', data).then((r) => r.data),
  get: (id: string) =>
    farmApi.get<CampaignOut>(`/campaigns/${id}`).then((r) => r.data),
  delete: (id: string) => farmApi.delete(`/campaigns/${id}`).then((r) => r.data),
  updateStatus: (id: string, status: CampaignStatus) =>
    farmApi.patch<CampaignOut>(`/campaigns/${id}/status`, { status }).then((r) => r.data),
  run: (id: string, deviceSerials?: string[]) =>
    farmApi
      .post<CampaignRunResponse>(`/campaigns/${id}/run`, deviceSerials?.length ? { device_serials_override: deviceSerials } : {})
      .then((r) => r.data),
  compileScenario: (
    id: string,
    options?: {
      instructions?: string;
      uiXml?: string;
      deviceSerial?: string;
      deviceContext?: Record<string, any>;
    }
  ) =>
    farmApi
      .post<CampaignOut>(`/campaigns/${id}/compile-scenario`, {
        ...(options?.instructions ? { instructions: options.instructions } : {}),
        ...(options?.uiXml ? { ui_xml: options.uiXml } : {}),
        ...(options?.deviceSerial ? { device_serial: options.deviceSerial } : {}),
        ...(options?.deviceContext && Object.keys(options.deviceContext).length
          ? { device_context: options.deviceContext }
          : {})
      })
      .then((r) => r.data),
  stepAction: (id: string, action: 'retry' | 'skip', deviceSerial?: string) =>
    farmApi
      .post<StepActionResponse>(`/campaigns/${id}/step-action`, {
        action,
        ...(deviceSerial ? { device_serial: deviceSerial } : {}),
      })
      .then((r) => r.data),
  getDevices: (id: string) =>
    farmApi.get<CampaignDeviceOut[]>(`/campaigns/${id}/devices`).then((r) => r.data),
  addDevice: (id: string, deviceId: string) =>
    farmApi.post(`/campaigns/${id}/devices`, { device_id: deviceId }).then((r) => r.data),
  removeDevice: (campaignId: string, deviceId: string) =>
    farmApi.delete(`/campaigns/${campaignId}/devices/${deviceId}`).then((r) => r.data),
  updateScenario: (id: string, scenario: Record<string, any>) =>
    farmApi
      .patch<CampaignOut>(`/campaigns/${id}/scenario`, { scenario })
      .then((r) => r.data),
  compileScenarioForScenario: (
    campaignId: string,
    scenarioId: string,
    options?: {
      instructions?: string;
      uiXml?: string;
      deviceSerial?: string;
      deviceContext?: Record<string, any>;
    }
  ) =>
    farmApi
      .post<ScenarioOut>(`/campaigns/${campaignId}/scenarios/${scenarioId}/compile`, {
        ...(options?.instructions ? { instructions: options.instructions } : {}),
        ...(options?.uiXml ? { ui_xml: options.uiXml } : {}),
        ...(options?.deviceSerial ? { device_serial: options.deviceSerial } : {}),
        ...(options?.deviceContext ? { device_context: options.deviceContext } : {})
      })
      .then((r) => r.data)
};

export const scenariosApi = {
  list: (campaignId: string) =>
    farmApi.get<ScenarioOut[]>(`/campaigns/${campaignId}/scenarios`).then((r) => r.data),
  create: (campaignId: string, data: ScenarioCreate) =>
    farmApi.post<ScenarioOut>(`/campaigns/${campaignId}/scenarios`, data).then((r) => r.data),
  get: (campaignId: string, scenarioId: string) =>
    farmApi.get<ScenarioOut>(`/campaigns/${campaignId}/scenarios/${scenarioId}`).then((r) => r.data),
  update: (campaignId: string, scenarioId: string, data: ScenarioUpdate) =>
    farmApi
      .patch<ScenarioOut>(`/campaigns/${campaignId}/scenarios/${scenarioId}`, data)
      .then((r) => r.data),
  delete: (campaignId: string, scenarioId: string) =>
    farmApi.delete(`/campaigns/${campaignId}/scenarios/${scenarioId}`).then((r) => r.data),
  compile: (
    campaignId: string,
    scenarioId: string,
    options?: {
      instructions?: string;
      uiXml?: string;
      deviceSerial?: string;
      deviceContext?: Record<string, any>;
    }
  ) =>
    farmApi
      .post<ScenarioOut>(`/campaigns/${campaignId}/scenarios/${scenarioId}/compile`, {
        ...(options?.instructions ? { instructions: options.instructions } : {}),
        ...(options?.uiXml ? { ui_xml: options.uiXml } : {}),
        ...(options?.deviceSerial ? { device_serial: options.deviceSerial } : {}),
        ...(options?.deviceContext ? { device_context: options.deviceContext } : {})
      })
      .then((r) => r.data)
};

export const workflowsApi = {
  listForCampaign: (campaignId: string) =>
    farmApi
      .get<CampaignWorkflowsResponse>(`/campaigns/${campaignId}/workflows`)
      .then((r) => r.data),
  progress: (workflowId: string) =>
    farmApi
      .get<WorkflowProgress>(`/workflows/${workflowId}/progress`)
      .then((r) => r.data),
  pause: (workflowId: string) =>
    farmApi.post(`/workflows/${workflowId}/pause`).then((r) => r.data),
  resume: (workflowId: string) =>
    farmApi.post(`/workflows/${workflowId}/resume`).then((r) => r.data),
  cancel: (workflowId: string) =>
    farmApi.post(`/workflows/${workflowId}/cancel`).then((r) => r.data),
  listForDevice: (serial: string) =>
    farmApi
      .get<{ serial: string; workflows: import('../types').WorkflowInfo[]; temporal_available: boolean }>(
        `/devices/${encodeURIComponent(serial)}/running-workflows`,
      )
      .then((r) => r.data),
  steps: (workflowId: string) =>
    farmApi
      .get<import('../types').WorkflowStepLog>(`/workflows/${encodeURIComponent(workflowId)}/steps`)
      .then((r) => r.data),
};

export const tasksApi = {
  list: (taskIds?: string[]) =>
    farmApi
      .get<TaskOut[]>(taskIds?.length ? `/tasks?ids=${taskIds.join(',')}` : '/tasks')
      .then((r) => r.data),
  listByPrefix: (namePrefix: string) =>
    farmApi
      .get<TaskOut[]>(`/tasks?name_prefix=${encodeURIComponent(namePrefix)}`)
      .then((r) => r.data)
};
