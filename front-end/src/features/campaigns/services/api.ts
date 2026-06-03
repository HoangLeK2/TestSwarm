import { farmApi } from '@/lib/farm-api';
import type {
  CampaignDispatchIn,
  CampaignDispatchOut,
  CampaignEntityOut,
  CampaignEntityUpdate,
  CampaignScenarioRefIn,
  CampaignAccountBindIn
} from '../../device-farm/services/generated/DeviceFarmApi';
import type {
  CampaignCreate,
  CampaignDeviceOut,
  CampaignOut,
  CampaignScenarioRefOut,
  CampaignRunResponse,
  CampaignStatus,
  CampaignWorkflowsResponse,
  ScenarioCreate,
  ScenarioOut,
  ScenarioUpdate,
  TaskOut,
  WorkflowProgress,
  DlqEntry,
  DlqBulkRetryResult,
  DlqSummary,
  ExecutionOut,
  ExecutionArtifact,
  ExecutionEventOut
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
  WorkflowProgress,
  DlqEntry,
  DlqBulkRetryResult,
  DlqSummary,
  ExecutionOut,
  ExecutionArtifact
} from '../types';

export type {
  CampaignDispatchIn,
  CampaignDispatchOut,
  CampaignEntityOut,
  CampaignEntityUpdate,
  CampaignScenarioRefIn,
  CampaignAccountBindIn
};

/** Extended dispatch execution row (DF-T-04-010 runtime fields). */
export type CampaignDispatchExecutionOut = {
  execution_id: string;
  device_id: string;
  status: string;
  effective_vars?: Record<string, unknown>;
  account_id?: string | null;
  failure_reason?: string | null;
  claim_session_id?: string | null;
  dispatch_source?: string | null;
  workflow_id?: string | null;
};

export type CampaignDispatchResponse = Omit<
  import('../../device-farm/services/generated/DeviceFarmApi').CampaignDispatchOut,
  'executions'
> & {
  executions?: CampaignDispatchExecutionOut[];
};

export type ExecutionRuntimeOut = {
  temporal: {
    enabled: boolean;
    server_url: string;
    namespace: string;
    task_queue: string;
  };
  campaign_run: {
    engine: string;
    dispatch_source: string;
    fallback_mode_active: boolean;
    note?: string;
  };
};

export function isCampaignEntityOut(
  value: CampaignOut | CampaignEntityOut | null | undefined
): value is CampaignEntityOut {
  if (value == null) return false;
  return (
    'organization_id' in value &&
    Array.isArray((value as CampaignEntityOut).scenario_refs)
  );
}

export function campaignVariables(
  value: CampaignOut | CampaignEntityOut | null | undefined
): Record<string, unknown> {
  if (!value) return {};
  if (isCampaignEntityOut(value)) return (value.vars ?? {}) as Record<string, unknown>;
  return (value.variables ?? {}) as Record<string, unknown>;
}

/** Map Epic-04 entity payloads to the shape list/detail UI expects (`scenario_refs`, `variables`, …). */
export function normalizeCampaignOut(
  raw: CampaignOut | CampaignEntityOut | Record<string, unknown> | null | undefined
): CampaignOut | null {
  if (raw == null) return null;
  const row = raw as CampaignEntityOut & CampaignOut;
  const vars = (row.vars ?? row.variables ?? {}) as Record<string, unknown>;
  const scenarioRefs = (row.scenario_refs ?? []) as CampaignScenarioRefOut[];

  if (row.organization_id) {
    return {
      id: row.id,
      name: row.name,
      description: row.description ?? null,
      status: row.status as CampaignOut['status'],
      organization_id: row.organization_id,
      scenario_refs: scenarioRefs,
      vars,
      variables: vars,
      tags: row.tags ?? [],
      created_at: String(row.created_at),
      updated_at: String(row.updated_at),
      user_id: row.created_by ?? row.user_id ?? null,
      devices: row.devices,
      target_group_id: row.target_group_id,
      scenario: row.scenario
    };
  }

  return {
    ...row,
    variables: row.variables ?? vars,
    scenario_refs: row.scenario_refs ?? scenarioRefs
  };
}

export type StepActionResponse = {
  action: string;
  signalled: string[];
  errors: string[];
  total: number;
};

export type CampaignControlResponse = {
  campaign_id: string;
  status: string;
  executions_affected: number;
  executions: Array<{
    execution_id: string;
    status: string;
    effective_transition: boolean;
    error?: string;
  }>;
  workflows_signalled?: number;
  warning?: string;
};

export type ScenarioDeviceVariablesOut = {
  scenario_id: string;
  device_id: string;
  vars: Record<string, unknown>;
};

export type ScenarioDeviceVariablesBody = {
  vars: Record<string, unknown>;
};

export const campaignsApi = {
  list: () =>
    farmApi
      .get<unknown>('/campaigns')
      .then((r) => {
        if (!Array.isArray(r.data)) {
          const raw =
            r.data === null
              ? 'null'
              : typeof r.data === 'string'
                ? r.data.slice(0, 200)
                : JSON.stringify(r.data).slice(0, 200);
          throw new Error(`Unexpected /campaigns response (non-array): ${raw}`);
        }
        return r.data
          .map((item) =>
            normalizeCampaignOut(item as CampaignOut | CampaignEntityOut)
          )
          .filter((item): item is CampaignOut => item != null);
      }),
  create: async (data: CampaignCreate) => {
    const r = await farmApi.post<CampaignOut | CampaignEntityOut>(
      '/campaigns',
      data
    );
    const row = normalizeCampaignOut(r.data);
    if (row) return row;
    if (r.status >= 200 && r.status < 300) {
      const nameKey = data.name.trim().toLowerCase();
      const listed = await campaignsApi.list();
      const match = listed.find(
        (c) => c.name.trim().toLowerCase() === nameKey
      );
      if (match) return match;
    }
    throw new Error('Campaign create returned an empty response body');
  },
  get: (id: string) =>
    farmApi
      .get<CampaignOut | CampaignEntityOut>(`/campaigns/${id}`)
      .then((r) => {
        const row = normalizeCampaignOut(r.data);
        if (!row) {
          throw new Error('Campaign not found');
        }
        return row;
      }),
  patchEntity: (id: string, data: CampaignEntityUpdate) =>
    farmApi
      .patch<CampaignEntityOut>(`/campaigns/${id}`, data)
      .then((r) => r.data),
  bindAccounts: (id: string, data: CampaignAccountBindIn) =>
    farmApi
      .post<CampaignEntityOut>(`/campaigns/${id}/accounts`, data)
      .then((r) => r.data),
  unbindAccounts: (id: string) =>
    farmApi
      .delete<CampaignEntityOut>(`/campaigns/${id}/accounts`)
      .then((r) => r.data),
  delete: (id: string) =>
    farmApi.delete<CampaignEntityOut>(`/campaigns/${id}`).then((r) => r.data),
  updateStatus: (id: string, status: CampaignStatus) =>
    farmApi
      .patch<CampaignOut>(`/campaigns/${id}/status`, { status })
      .then((r) => r.data),
  pause: (id: string) =>
    farmApi
      .post<CampaignControlResponse>(`/campaigns/${id}/pause`)
      .then((r) => r.data),
  resume: (id: string) =>
    farmApi
      .post<CampaignControlResponse>(`/campaigns/${id}/resume`)
      .then((r) => r.data),
  cancel: (id: string, reason?: string) =>
    farmApi
      .post<CampaignControlResponse>(`/campaigns/${id}/cancel`, {
        reason: reason ?? ''
      })
      .then((r) => r.data),
  dispatch: (id: string, body: CampaignDispatchIn) =>
    farmApi
      .post<CampaignDispatchResponse>(`/campaigns/${id}/dispatch`, body)
      .then((r) => r.data),
  run: (id: string, deviceSerials?: string[]) =>
    farmApi
      .post<CampaignRunResponse>(
        `/campaigns/${id}/run`,
        deviceSerials?.length ? { device_serials_override: deviceSerials } : {}
      )
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
        ...(options?.instructions
          ? { instructions: options.instructions }
          : {}),
        ...(options?.uiXml ? { ui_xml: options.uiXml } : {}),
        ...(options?.deviceSerial
          ? { device_serial: options.deviceSerial }
          : {}),
        ...(options?.deviceContext && Object.keys(options.deviceContext).length
          ? { device_context: options.deviceContext }
          : {})
      })
      .then((r) => r.data),
  stepAction: (id: string, action: 'retry' | 'skip', deviceSerial?: string) =>
    farmApi
      .post<StepActionResponse>(`/campaigns/${id}/step-action`, {
        action,
        ...(deviceSerial ? { device_serial: deviceSerial } : {})
      })
      .then((r) => r.data),
  getDevices: (id: string) =>
    farmApi
      .get<CampaignDeviceOut[]>(`/campaigns/${id}/devices`)
      .then((r) => r.data),
  addDevice: (id: string, deviceId: string) =>
    farmApi
      .post(`/campaigns/${id}/devices`, { device_id: deviceId })
      .then((r) => r.data),
  removeDevice: (campaignId: string, deviceId: string) =>
    farmApi
      .delete(`/campaigns/${campaignId}/devices/${deviceId}`)
      .then((r) => r.data),
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
      .post<ScenarioOut>(
        `/campaigns/${campaignId}/scenarios/${scenarioId}/compile`,
        {
          ...(options?.instructions
            ? { instructions: options.instructions }
            : {}),
          ...(options?.uiXml ? { ui_xml: options.uiXml } : {}),
          ...(options?.deviceSerial
            ? { device_serial: options.deviceSerial }
            : {}),
          ...(options?.deviceContext
            ? { device_context: options.deviceContext }
            : {})
        }
      )
      .then((r) => r.data),
  getScenarioDeviceVariables: (
    campaignId: string,
    scenarioId: string,
    deviceId: string
  ) =>
    farmApi
      .get<ScenarioDeviceVariablesOut>(
        `/campaigns/${campaignId}/scenarios/${scenarioId}/devices/${deviceId}/variables`
      )
      .then((r) => r.data),
  replaceScenarioDeviceVariables: (
    campaignId: string,
    scenarioId: string,
    deviceId: string,
    body: ScenarioDeviceVariablesBody
  ) =>
    farmApi
      .put<ScenarioDeviceVariablesOut>(
        `/campaigns/${campaignId}/scenarios/${scenarioId}/devices/${deviceId}/variables`,
        body
      )
      .then((r) => r.data)
};

export const executionRuntimeApi = {
  get: () =>
    farmApi.get<ExecutionRuntimeOut>('/execution/runtime').then((r) => r.data)
};

export const scenariosApi = {
  list: (campaignId: string) =>
    farmApi
      .get<ScenarioOut[]>(`/campaigns/${campaignId}/scenarios`)
      .then((r) => r.data),
  create: (campaignId: string, data: ScenarioCreate) =>
    farmApi
      .post<ScenarioOut>(`/campaigns/${campaignId}/scenarios`, data)
      .then((r) => r.data),
  get: (campaignId: string, scenarioId: string) =>
    farmApi
      .get<ScenarioOut>(`/campaigns/${campaignId}/scenarios/${scenarioId}`)
      .then((r) => r.data),
  update: (campaignId: string, scenarioId: string, data: ScenarioUpdate) =>
    farmApi
      .patch<ScenarioOut>(
        `/campaigns/${campaignId}/scenarios/${scenarioId}`,
        data
      )
      .then((r) => r.data),
  delete: (campaignId: string, scenarioId: string) =>
    farmApi
      .delete(`/campaigns/${campaignId}/scenarios/${scenarioId}`)
      .then((r) => r.data),
  reorder: (campaignId: string, orderedIds: string[]) =>
    farmApi
      .post<
        ScenarioOut[]
      >(`/campaigns/${campaignId}/scenarios/reorder`, { ordered_ids: orderedIds })
      .then((r) => r.data),
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
      .post<ScenarioOut>(
        `/campaigns/${campaignId}/scenarios/${scenarioId}/compile`,
        {
          ...(options?.instructions
            ? { instructions: options.instructions }
            : {}),
          ...(options?.uiXml ? { ui_xml: options.uiXml } : {}),
          ...(options?.deviceSerial
            ? { device_serial: options.deviceSerial }
            : {}),
          ...(options?.deviceContext
            ? { device_context: options.deviceContext }
            : {})
        }
      )
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
    farmApi
      .post(`/workflows/${encodeURIComponent(workflowId)}/pause`)
      .then((r) => r.data),
  resume: (workflowId: string) =>
    farmApi
      .post(`/workflows/${encodeURIComponent(workflowId)}/resume`)
      .then((r) => r.data),
  cancel: (workflowId: string) =>
    farmApi
      .post(`/workflows/${encodeURIComponent(workflowId)}/cancel`)
      .then((r) => r.data),
  listForDevice: (serial: string) =>
    farmApi
      .get<{
        serial: string;
        workflows: import('../types').WorkflowInfo[];
        temporal_available: boolean;
      }>(`/devices/${encodeURIComponent(serial)}/running-workflows`)
      .then((r) => r.data),
  steps: (workflowId: string) =>
    farmApi
      .get<
        import('../types').WorkflowStepLog
      >(`/workflows/${encodeURIComponent(workflowId)}/steps`)
      .then((r) => r.data)
};

export const tasksApi = {
  list: (taskIds?: string[]) =>
    farmApi
      .get<
        TaskOut[]
      >(taskIds?.length ? `/tasks?ids=${taskIds.join(',')}` : '/tasks')
      .then((r) => r.data),
  listByPrefix: (namePrefix: string) =>
    farmApi
      .get<TaskOut[]>(`/tasks?name_prefix=${encodeURIComponent(namePrefix)}`)
      .then((r) => r.data)
};

export const dlqApi = {
  list: (params?: {
    status?: string;
    campaignId?: string;
    offset?: number;
    limit?: number;
  }) =>
    farmApi
      .get<DlqEntry[]>('/executions/dlq', {
        params: {
          ...(params?.status ? { status: params.status } : {}),
          ...(params?.campaignId ? { campaign_id: params.campaignId } : {}),
          ...(params?.offset != null ? { offset: params.offset } : {}),
          ...(params?.limit != null ? { limit: params.limit } : {})
        }
      })
      .then((r) => r.data),
  getByExecution: (executionId: string) =>
    farmApi
      .get<DlqEntry>(`/executions/dlq/executions/${encodeURIComponent(executionId)}`)
      .then((r) => r.data),
  summary: (params?: { campaignId?: string }) =>
    farmApi
      .get<DlqSummary>('/executions/dlq/summary', {
        params: {
          ...(params?.campaignId ? { campaign_id: params.campaignId } : {})
        }
      })
      .then((r) => r.data),
  retry: (dlqId: string, options?: { fromCheckpoint?: boolean }) =>
    farmApi
      .post<DlqEntry>(`/executions/dlq/${encodeURIComponent(dlqId)}/retry`, {
        from_checkpoint: options?.fromCheckpoint ?? true
      })
      .then((r) => r.data),
  close: (dlqId: string, reason: string) =>
    farmApi
      .post<DlqEntry>(`/executions/dlq/${encodeURIComponent(dlqId)}/close`, {
        reason
      })
      .then((r) => r.data),
  bulkRetry: (payload: {
    executionIds?: string[];
    dlqIds?: string[];
    fromCheckpoint?: boolean;
  }) =>
    farmApi
      .post<{ results: DlqBulkRetryResult[] }>('/executions/dlq/bulk-retry', {
        execution_ids: payload.executionIds ?? [],
        dlq_ids: payload.dlqIds ?? [],
        from_checkpoint: payload.fromCheckpoint ?? true
      })
      .then((r) => r.data.results),
  dismiss: (dlqId: string) =>
    farmApi
      .delete(`/executions/dlq/${encodeURIComponent(dlqId)}`)
      .then((r) => r.data)
};

export type ExecutionControlOut = {
  execution_id: string;
  status: string;
  action: string;
  effective_transition: boolean;
  workflows_signalled?: number;
  warning?: string | null;
};

export const executionsApi = {
  list: (params?: { campaignId?: string; limit?: number; offset?: number }) =>
    farmApi
      .get<{ total: number; items: ExecutionOut[] }>('/executions', {
        params: {
          ...(params?.campaignId ? { campaign_id: params.campaignId } : {}),
          ...(params?.limit != null ? { limit: params.limit } : {}),
          ...(params?.offset != null ? { offset: params.offset } : {})
        }
      })
      .then((r) => r.data),
  summary: (executionId: string) =>
    farmApi
      .get<{
        total_devices: number;
        passed: number;
        failed: number;
        running: number;
        pending: number;
        error: number;
        total_content_items: number;
      }>(`/executions/${encodeURIComponent(executionId)}/summary`)
      .then((r) => r.data),
  listArtifacts: (executionId: string) =>
    farmApi
      .get<
        ExecutionArtifact[]
      >(`/executions/${encodeURIComponent(executionId)}/artifacts`)
      .then((r) => r.data),
  listEvents: (
    executionId: string,
    params?: { since?: string | null; limit?: number }
  ) =>
    farmApi
      .get<{ items: ExecutionEventOut[]; has_more?: boolean }>(
        `/executions/${encodeURIComponent(executionId)}/events`,
        {
          params: {
            ...(params?.since ? { since: params.since } : {}),
            ...(params?.limit != null ? { limit: params.limit } : {})
          }
        }
      )
      .then((r) => r.data),
  pause: (executionId: string) =>
    farmApi
      .post<ExecutionControlOut>(
        `/executions/${encodeURIComponent(executionId)}/pause`
      )
      .then((r) => r.data),
  resume: (executionId: string) =>
    farmApi
      .post<ExecutionControlOut>(
        `/executions/${encodeURIComponent(executionId)}/resume`
      )
      .then((r) => r.data),
  cancel: (executionId: string, reason?: string) =>
    farmApi
      .post<ExecutionControlOut>(
        `/executions/${encodeURIComponent(executionId)}/cancel`,
        reason ? { reason } : {}
      )
      .then((r) => r.data)
};
