'use client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient
} from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import {
  campaignsApi,
  dlqApi,
  executionRuntimeApi,
  executionsApi,
  normalizeCampaignOut,
  scenariosApi,
  tasksApi,
  workflowsApi,
  type CampaignEntityUpdate
} from '../services/api';
import type {
  CampaignAccountBindIn,
  CampaignDispatchIn
} from '../../device-farm/services/generated/DeviceFarmApi';
import {
  isCampaignActiveExecution,
  isCampaignTerminal,
  type CampaignCreate,
  type CampaignOut,
  type CampaignRunResponse,
  type CampaignStatus,
  type ScenarioCreate,
  type ScenarioOut,
  type ScenarioUpdate
} from '../types';
import {
  fleetRun,
  fleetStatus,
  type FleetStatusResult
} from '../../devices/services/api';
import { markCampaignStopDrain } from './use-campaign-stop-drain';
import {
  summarizeDispatchResult,
  type DispatchResultSummary
} from '../lib/campaign-dispatch-result';

const KEYS = {
  list: ['campaigns'] as const,
  detail: (id: string) => ['campaigns', id] as const,
  devices: (id: string) => ['campaigns', id, 'devices'] as const,
  scenarios: (campaignId: string) =>
    ['campaigns', campaignId, 'scenarios'] as const,
  executionRuntime: ['execution-runtime'] as const
};

/** Shared poll tuning — reduces API spam when monitor / campaigns are open. */
const CAMPAIGN_LIST_ACTIVE_POLL_MS = 15_000;
const MONITOR_WORKFLOW_POLL_MS = 12_000;
const MONITOR_EXECUTION_POLL_MS = 20_000;
const MONITOR_SIDEBAR_ACTIVE_POLL_MS = 30_000;
const MONITOR_SIDEBAR_IDLE_POLL_MS = 60_000;
const WORKFLOW_PROGRESS_POLL_MS = 8_000;
const WORKFLOW_STEPS_POLL_MS = 15_000;

const monitorQueryDefaults = {
  refetchOnWindowFocus: false
} as const;

function byScenarioOrder(a: ScenarioOut, b: ScenarioOut) {
  return (a.order ?? 0) - (b.order ?? 0);
}

function upsertScenarioRow(rows: ScenarioOut[], row: ScenarioOut) {
  const found = rows.some((s) => s.id === row.id);
  const next = found
    ? rows.map((s) => (s.id === row.id ? row : s))
    : [...rows, row];
  return [...next].sort(byScenarioOrder);
}

function updateCachedCampaignScenarios(
  qc: QueryClient,
  campaignId: string,
  update: (rows: ScenarioOut[]) => ScenarioOut[]
) {
  qc.setQueryData<ScenarioOut[]>(KEYS.scenarios(campaignId), (old) =>
    update(old ?? [])
  );
  qc.setQueryData<CampaignOut | undefined>(KEYS.detail(campaignId), (old) =>
    old ? { ...old, scenarios: update(old.scenarios ?? []) } : old
  );
  qc.setQueryData<CampaignOut[] | undefined>(KEYS.list, (old) =>
    old?.map((campaign) =>
      campaign.id === campaignId
        ? { ...campaign, scenarios: update(campaign.scenarios ?? []) }
        : campaign
    )
  );
}

function invalidateCampaignScenarioQueries(
  qc: QueryClient,
  campaignId: string
) {
  qc.invalidateQueries({ queryKey: KEYS.scenarios(campaignId), exact: true });
  qc.invalidateQueries({ queryKey: KEYS.detail(campaignId), exact: true });
  qc.invalidateQueries({ queryKey: KEYS.list, exact: true });
}

export function useExecutionRuntime() {
  return useQuery({
    queryKey: KEYS.executionRuntime,
    queryFn: executionRuntimeApi.get,
    staleTime: 60_000
  });
}

export function useCampaigns() {
  const qc = useQueryClient();
  return useQuery({
    queryKey: KEYS.list,
    queryFn: async () => {
      const fetched = await campaignsApi.list();
      const cached = qc.getQueryData<CampaignOut[]>(KEYS.list) ?? [];
      if (!cached.length) return fetched;
      const byId = new Map(fetched.map((c) => [c.id, c]));
      for (const row of cached) {
        if (!row?.id) continue;
        if (!byId.has(row.id)) byId.set(row.id, row);
      }
      return Array.from(byId.values()).sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      );
    },
    refetchInterval: (query) => {
      const data = query.state.data as CampaignOut[] | undefined;
      return data &&
        data.some((c: CampaignOut) => isCampaignActiveExecution(c.status))
        ? CAMPAIGN_LIST_ACTIVE_POLL_MS
        : false;
    }
  });
}

export function useCampaign(id: string, enabled = true) {
  return useQuery({
    queryKey: KEYS.detail(id),
    queryFn: () => campaignsApi.get(id),
    enabled: enabled && !!id
  });
}

export function useCampaignDevices(campaignId: string, enabled = true) {
  return useQuery({
    queryKey: KEYS.devices(campaignId),
    queryFn: () => campaignsApi.getDevices(campaignId),
    enabled: enabled && !!campaignId
  });
}

export function useAddDeviceToCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      campaignId,
      deviceId
    }: {
      campaignId: string;
      deviceId: string;
    }) => campaignsApi.addDevice(campaignId, deviceId),
    onSuccess: (_, { campaignId }) => {
      qc.invalidateQueries({ queryKey: KEYS.devices(campaignId) });
      qc.invalidateQueries({ queryKey: KEYS.list });
    }
  });
}

export function useRemoveDeviceFromCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      campaignId,
      deviceId
    }: {
      campaignId: string;
      deviceId: string;
    }) => campaignsApi.removeDevice(campaignId, deviceId),
    onSuccess: (_, { campaignId }) => {
      qc.invalidateQueries({ queryKey: KEYS.devices(campaignId) });
      qc.invalidateQueries({ queryKey: KEYS.list });
    }
  });
}

export function useCreateCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CampaignCreate) => campaignsApi.create(data),
    onSuccess: (created) => {
      const row =
        created && typeof created === 'object' && 'id' in created
          ? normalizeCampaignOut(created)
          : null;
      if (!row?.id) return;
      qc.setQueryData(KEYS.detail(row.id), row);
      qc.setQueryData<CampaignOut[]>(KEYS.list, (prev) => {
        const list = prev ?? [];
        if (list.some((c) => c.id === row.id)) {
          return list.map((c) => (c.id === row.id ? row : c));
        }
        return [row, ...list];
      });
    }
  });
}

export function useUpdateCampaignStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: CampaignStatus }) =>
      campaignsApi.updateStatus(id, status),
    onMutate: async ({ id, status }) => {
      await Promise.all([
        qc.cancelQueries({ queryKey: KEYS.list }),
        qc.cancelQueries({ queryKey: KEYS.detail(id) })
      ]);
      const previousList = qc.getQueryData<CampaignOut[]>(KEYS.list);
      const previousDetail = qc.getQueryData<CampaignOut>(KEYS.detail(id));
      qc.setQueryData<CampaignOut[] | undefined>(KEYS.list, (old) =>
        old?.map((campaign) =>
          campaign.id === id ? { ...campaign, status } : campaign
        )
      );
      qc.setQueryData<CampaignOut | undefined>(KEYS.detail(id), (old) =>
        old ? { ...old, status } : old
      );
      return { previousList, previousDetail };
    },
    onError: (_error, { id }, context) => {
      if (context?.previousList) {
        qc.setQueryData(KEYS.list, context.previousList);
      }
      if (context?.previousDetail) {
        qc.setQueryData(KEYS.detail(id), context.previousDetail);
      }
    },
    onSuccess: async (_data, { id }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(id) });
      qc.invalidateQueries({ queryKey: ['campaign-workflows', id] });
      await Promise.all([
        qc.refetchQueries({ queryKey: KEYS.list }),
        qc.refetchQueries({ queryKey: KEYS.detail(id) }),
        qc.refetchQueries({ queryKey: ['campaign-workflows', id] })
      ]);
    }
  });
}

export function usePatchCampaignEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: CampaignEntityUpdate }) =>
      campaignsApi.patchEntity(id, data),
    onSuccess: (data, { id }) => {
      const campaign = normalizeCampaignOut(data);
      if (campaign) {
        qc.setQueryData(KEYS.detail(id), campaign);
        qc.setQueryData(['campaign', id, 'global-vars-preview'], campaign);
        qc.setQueryData<CampaignOut[] | undefined>(KEYS.list, (old) =>
          old?.map((row) => (row.id === id ? { ...row, ...campaign } : row))
        );
      }
      qc.invalidateQueries({ queryKey: KEYS.list, exact: true });
      qc.invalidateQueries({ queryKey: KEYS.detail(id), exact: true });
      qc.invalidateQueries({
        queryKey: ['campaign', id, 'global-vars-preview'],
        exact: true
      });
    }
  });
}

export function useBindCampaignAccounts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: CampaignAccountBindIn }) =>
      campaignsApi.bindAccounts(id, data),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(id) });
    }
  });
}

export function useUnbindCampaignAccounts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => campaignsApi.unbindAccounts(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(id) });
    }
  });
}

export function useDeleteCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => campaignsApi.delete(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: KEYS.list });
      const previousList = qc.getQueryData<CampaignOut[]>(KEYS.list);
      qc.setQueryData<CampaignOut[] | undefined>(KEYS.list, (old) =>
        old?.filter((campaign) => campaign.id !== id)
      );
      return { previousList };
    },
    onError: (_error, _id, context) => {
      if (context?.previousList) {
        qc.setQueryData(KEYS.list, context.previousList);
      }
    },
    onSuccess: (_data, id) => {
      qc.removeQueries({ queryKey: KEYS.detail(id) });
      qc.invalidateQueries({ queryKey: KEYS.list });
    }
  });
}

export function useUpdateCampaignScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      scenario
    }: {
      id: string;
      scenario: Record<string, any>;
    }) => campaignsApi.updateScenario(id, scenario),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(id) });
    }
  });
}

export function useCompileCampaignScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: {
      id: string;
      instructions?: string;
      uiXml?: string;
      deviceSerial?: string;
      deviceContext?: Record<string, any>;
    }) =>
      campaignsApi.compileScenario(params.id, {
        instructions: params.instructions,
        uiXml: params.uiXml,
        deviceSerial: params.deviceSerial,
        deviceContext: params.deviceContext
      }),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(id) });
    }
  });
}

/** Poll task progress for a campaign by name prefix (campaign:{id}:*). */
export function useCampaignProgress(campaignId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['campaign-progress', campaignId],
    queryFn: () => tasksApi.listByPrefix(`campaign:${campaignId}:`),
    enabled,
    refetchInterval: (query) => {
      const tasks = query.state.data as any[] | undefined;
      if (query.state.error) return false;
      // Wait for the first fetch result; then only keep polling while there are
      // active tasks. This prevents /api/tasks spam when no tasks exist.
      if (!tasks) return 2000;
      if (tasks.length === 0) return false;
      const hasActiveTask = tasks.some(
        (t) => t.status !== 'DONE' && t.status !== 'FAILED'
      );
      return hasActiveTask ? 2000 : false;
    },
    select: (tasks) => {
      const total = tasks.length;
      const done = tasks.filter((t) => t.status === 'DONE').length;
      const failed = tasks.filter((t) => t.status === 'FAILED').length;
      const running = tasks.filter((t) => t.status === 'RUNNING').length;
      const pending = tasks.filter((t) => t.status === 'PENDING').length;
      const terminal = done + failed;
      return {
        total,
        done,
        failed,
        running,
        pending,
        pct: total ? Math.round((terminal / total) * 100) : 0
      };
    }
  });
}

// ── Scenario hooks ────────────────────────────────────────────────────────────

export function useScenarios(campaignId: string, enabled = true) {
  return useQuery({
    queryKey: KEYS.scenarios(campaignId),
    queryFn: () => scenariosApi.list(campaignId),
    enabled: enabled && !!campaignId
  });
}

export function useCreateScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      campaignId,
      data
    }: {
      campaignId: string;
      data: ScenarioCreate;
    }) => scenariosApi.create(campaignId, data),
    onSuccess: (created, { campaignId }) => {
      updateCachedCampaignScenarios(qc, campaignId, (rows) =>
        upsertScenarioRow(rows, created)
      );
      invalidateCampaignScenarioQueries(qc, campaignId);
    }
  });
}

export function useUpdateScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      campaignId,
      scenarioId,
      data
    }: {
      campaignId: string;
      scenarioId: string;
      data: ScenarioUpdate;
    }) => scenariosApi.update(campaignId, scenarioId, data),
    onSuccess: (updated, { campaignId }) => {
      updateCachedCampaignScenarios(qc, campaignId, (rows) =>
        upsertScenarioRow(rows, updated)
      );
      invalidateCampaignScenarioQueries(qc, campaignId);
    }
  });
}

export function useDeleteScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      campaignId,
      scenarioId
    }: {
      campaignId: string;
      scenarioId: string;
    }) => scenariosApi.delete(campaignId, scenarioId),
    onSuccess: (_, { campaignId, scenarioId }) => {
      updateCachedCampaignScenarios(qc, campaignId, (rows) =>
        rows.filter((scenario) => scenario.id !== scenarioId)
      );
      invalidateCampaignScenarioQueries(qc, campaignId);
    }
  });
}

export function useReorderScenarios() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      campaignId,
      orderedIds
    }: {
      campaignId: string;
      orderedIds: string[];
    }) => scenariosApi.reorder(campaignId, orderedIds),
    onSuccess: (data, { campaignId }) => {
      updateCachedCampaignScenarios(qc, campaignId, () => data);
      invalidateCampaignScenarioQueries(qc, campaignId);
    }
  });
}

export function useCompileScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: {
      campaignId: string;
      scenarioId: string;
      instructions?: string;
      uiXml?: string;
      deviceSerial?: string;
      deviceContext?: Record<string, any>;
    }) =>
      scenariosApi.compile(params.campaignId, params.scenarioId, {
        instructions: params.instructions,
        uiXml: params.uiXml,
        deviceSerial: params.deviceSerial,
        deviceContext: params.deviceContext
      }),
    onSuccess: (updated, { campaignId }) => {
      updateCachedCampaignScenarios(qc, campaignId, (rows) =>
        upsertScenarioRow(rows, updated)
      );
      invalidateCampaignScenarioQueries(qc, campaignId);
    }
  });
}

// ── Temporal Workflow hooks ──────────────────────────────────────────────────

export function useCampaignWorkflows(campaignId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['campaign-workflows', campaignId],
    queryFn: () => workflowsApi.listForCampaign(campaignId),
    enabled,
    ...monitorQueryDefaults,
    refetchInterval: enabled ? MONITOR_WORKFLOW_POLL_MS : false
  });
}

/** Running/pending executions for workflow → execution_id resolution (DF-T-04-013 SSE). */
export function useCampaignExecutions(campaignId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['campaign-executions', campaignId],
    queryFn: () => executionsApi.list({ campaignId, limit: 200 }),
    enabled: enabled && !!campaignId,
    select: (data) => data.items,
    staleTime: 10_000,
    ...monitorQueryDefaults,
    refetchInterval: enabled ? MONITOR_EXECUTION_POLL_MS : false
  });
}

export function useDeviceRunningWorkflows(serial: string, enabled: boolean) {
  return useQuery({
    queryKey: ['device-running-workflows', serial],
    queryFn: () => workflowsApi.listForDevice(serial),
    enabled: enabled && !!serial,
    ...monitorQueryDefaults,
    refetchInterval: enabled ? MONITOR_WORKFLOW_POLL_MS : false
  });
}

export function useWorkflowSteps(
  workflowId: string,
  enabled: boolean,
  poll = enabled
) {
  return useQuery({
    queryKey: ['workflow-steps', workflowId],
    queryFn: () => workflowsApi.steps(workflowId),
    enabled: enabled && !!workflowId,
    ...monitorQueryDefaults,
    staleTime: 5_000,
    refetchInterval: enabled && poll ? WORKFLOW_STEPS_POLL_MS : false
  });
}

export function useWorkflowProgress(workflowId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['workflow-progress', workflowId],
    queryFn: () => workflowsApi.progress(workflowId),
    enabled: enabled && !!workflowId,
    ...monitorQueryDefaults,
    staleTime: 3_000,
    refetchInterval: enabled ? WORKFLOW_PROGRESS_POLL_MS : false
  });
}

function useInvalidateCampaignControl(qc: ReturnType<typeof useQueryClient>) {
  return (campaignId: string) => {
    qc.invalidateQueries({ queryKey: KEYS.list });
    qc.invalidateQueries({ queryKey: KEYS.detail(campaignId) });
    qc.invalidateQueries({ queryKey: ['campaign-workflows', campaignId] });
    qc.invalidateQueries({ queryKey: ['campaign-workflows'] });
  };
}

export function useCampaignPause() {
  const qc = useQueryClient();
  const invalidate = useInvalidateCampaignControl(qc);
  return useMutation({
    mutationFn: (campaignId: string) => campaignsApi.pause(campaignId),
    onSuccess: (_data, campaignId) => invalidate(campaignId)
  });
}

export function useCampaignResume() {
  const qc = useQueryClient();
  const invalidate = useInvalidateCampaignControl(qc);
  return useMutation({
    mutationFn: (campaignId: string) => campaignsApi.resume(campaignId),
    onSuccess: (_data, campaignId) => invalidate(campaignId)
  });
}

export function useCampaignCancel() {
  const qc = useQueryClient();
  const invalidate = useInvalidateCampaignControl(qc);
  return useMutation({
    mutationFn: ({
      campaignId,
      reason
    }: {
      campaignId: string;
      reason?: string;
    }) => campaignsApi.cancel(campaignId, reason),
    onSuccess: (data, { campaignId }) => {
      markCampaignStopDrain(qc, campaignId, {
        workflowsSignalled: data.workflows_signalled,
        notifyOnComplete: true
      });
      invalidate(campaignId);
    }
  });
}

export {
  useCampaignStopDrain,
  markCampaignStopDrain
} from './use-campaign-stop-drain';

export function useWorkflowPause() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (workflowId: string) => workflowsApi.pause(workflowId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-workflows'] });
    }
  });
}

export function useWorkflowResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (workflowId: string) => workflowsApi.resume(workflowId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-workflows'] });
    }
  });
}

export function useWorkflowCancel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (workflowId: string) => workflowsApi.cancel(workflowId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-workflows'] });
    }
  });
}

export function useStepAction(campaignId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      action,
      deviceSerial
    }: {
      action: 'retry' | 'skip';
      deviceSerial?: string;
    }) => campaignsApi.stepAction(campaignId, action, deviceSerial),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workflow-progress'] });
      qc.invalidateQueries({ queryKey: ['campaign-workflows', campaignId] });
    }
  });
}

export function useDlqEntries(
  enabled: boolean,
  status?: string,
  campaignId?: string,
  pollAggressive = true
) {
  return useQuery({
    queryKey: ['dlq-entries', status ?? 'all', campaignId ?? 'global'],
    queryFn: () =>
      dlqApi.list({ status: status ?? 'open', campaignId, limit: 100 }),
    enabled,
    ...monitorQueryDefaults,
    refetchInterval: enabled
      ? pollAggressive
        ? MONITOR_SIDEBAR_ACTIVE_POLL_MS
        : MONITOR_SIDEBAR_IDLE_POLL_MS
      : false
  });
}

export function useDlqEntryByExecution(
  executionId: string | undefined,
  enabled: boolean
) {
  return useQuery({
    queryKey: ['dlq-entry', executionId],
    queryFn: () => dlqApi.getByExecution(executionId!),
    enabled: enabled && !!executionId
  });
}

export function useDlqSummary(
  enabled: boolean,
  campaignId?: string,
  pollAggressive = true
) {
  return useQuery({
    queryKey: ['dlq-summary', campaignId ?? 'global'],
    queryFn: () => dlqApi.summary({ campaignId }),
    enabled,
    ...monitorQueryDefaults,
    refetchInterval: enabled
      ? pollAggressive
        ? MONITOR_SIDEBAR_ACTIVE_POLL_MS
        : MONITOR_SIDEBAR_IDLE_POLL_MS
      : false
  });
}

export function useRetryDlqEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      dlqId,
      fromCheckpoint = true
    }: {
      dlqId: string;
      fromCheckpoint?: boolean;
    }) => dlqApi.retry(dlqId, { fromCheckpoint }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dlq-entries'] });
      qc.invalidateQueries({ queryKey: ['dlq-summary'] });
      qc.invalidateQueries({ queryKey: ['campaign-workflows'] });
      qc.invalidateQueries({ queryKey: ['workflow-progress'] });
    }
  });
}

export function useCloseDlqEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ dlqId, reason }: { dlqId: string; reason: string }) =>
      dlqApi.close(dlqId, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dlq-entries'] });
      qc.invalidateQueries({ queryKey: ['dlq-summary'] });
      qc.invalidateQueries({ queryKey: ['campaign-workflows'] });
    }
  });
}

export function useBulkRetryDlq() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      executionIds?: string[];
      dlqIds?: string[];
      fromCheckpoint?: boolean;
    }) => dlqApi.bulkRetry(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dlq-entries'] });
      qc.invalidateQueries({ queryKey: ['dlq-summary'] });
      qc.invalidateQueries({ queryKey: ['campaign-workflows'] });
      qc.invalidateQueries({ queryKey: ['workflow-progress'] });
    }
  });
}

export function useDismissDlqEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (dlqId: string) => dlqApi.dismiss(dlqId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dlq-entries'] });
      qc.invalidateQueries({ queryKey: ['dlq-summary'] });
    }
  });
}

export function useExecutionArtifacts(
  executionId: string | null | undefined,
  enabled: boolean,
  pollAggressive = true
) {
  return useQuery({
    queryKey: ['execution-artifacts', executionId],
    enabled: enabled && !!executionId,
    ...monitorQueryDefaults,
    staleTime: 10 * 60_000,
    gcTime: 30 * 60_000,
    queryFn: () => executionsApi.listArtifacts(executionId!),
    refetchInterval:
      enabled && pollAggressive ? MONITOR_SIDEBAR_ACTIVE_POLL_MS : false,
    refetchOnWindowFocus: false
  });
}

export function useCampaignExecutionHistory(
  campaignId: string,
  enabled: boolean,
  pollAggressive = true
) {
  return useQuery({
    queryKey: ['campaign-execution-history', campaignId],
    enabled: enabled && !!campaignId,
    ...monitorQueryDefaults,
    staleTime: 15_000,
    queryFn: () => executionsApi.list({ campaignId, limit: 50, offset: 0 }),
    select: (data) => data.items ?? [],
    refetchInterval: enabled
      ? pollAggressive
        ? MONITOR_SIDEBAR_ACTIVE_POLL_MS
        : MONITOR_SIDEBAR_IDLE_POLL_MS
      : false
  });
}

// ── Fleet run ─────────────────────────────────────────────────────────────────

/** Fleet run: dispatch campaign scenario to ALL READY devices. */
export function useFleetRunCampaign(
  onDone?: (result: FleetStatusResult) => void
) {
  const mutation = useMutation({
    mutationFn: (campaign: CampaignOut) => {
      const scenarios = campaign.scenarios ?? [];
      const steps = scenarios.flatMap((s) => s.steps);
      if (!Array.isArray(steps) || !steps.length) {
        return Promise.reject(
          new Error(
            'Campaign chưa có kịch bản (steps). Hãy thiết lập kịch bản trước.'
          )
        );
      }
      return fleetRun(steps as Array<Record<string, unknown>>);
    },
    onSuccess: (data) => {
      const deadline = Date.now() + 10 * 60 * 1000;
      const t = setInterval(async () => {
        if (Date.now() > deadline) {
          clearInterval(t);
          return;
        }
        try {
          const s = await fleetStatus(data.run_id);
          if (s.all_complete) {
            clearInterval(t);
            onDone?.(s);
          }
        } catch {
          /* ignore */
        }
      }, 3000);
    }
  });
  return mutation;
}

const TERMINAL_STATUSES = [
  'DONE',
  'FAILED',
  'COMPLETED',
  'CANCELLED',
  'TERMINATED'
];
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 10 * 60 * 1000;

const _engineStorageKey = (campaignId: string) =>
  `df_campaign_engine:${campaignId}`;

export type RunCampaignOptions = {
  onTemporalFallback?: () => void;
};

export function useRunCampaign(
  onAllDone?: () => void,
  options?: RunCampaignOptions
) {
  const qc = useQueryClient();
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearPollTimer = () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  };

  useEffect(() => clearPollTimer, []);

  return useMutation({
    mutationFn: ({
      id,
      deviceSerials
    }: {
      id: string;
      deviceSerials?: string[];
    }) => campaignsApi.run(id, deviceSerials),
    onSuccess: async (data: CampaignRunResponse, { id }) => {
      // TODO(account-groups): when backend surfaces a warning field for
      // empty/exhausted account groups on CampaignRunResponse
      // (e.g. data.warnings or data.account_group_warning), call
      // toast.warning(...) here to surface it to the operator.
      clearPollTimer();
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(id) });

      const engine =
        data.execution_engine ??
        data.engine ??
        (data.workflow_ids?.length ? 'temporal' : 'task_queue');
      try {
        sessionStorage.setItem(_engineStorageKey(id), engine);
      } catch {
        /* private mode */
      }
      if (data.temporal_fallback) {
        options?.onTemporalFallback?.();
      }

      const resetToIdle = async () => {
        try {
          await campaignsApi.updateStatus(id, 'idle');
        } catch {
          /* ignore */
        }
        qc.invalidateQueries({ queryKey: KEYS.list });
        qc.invalidateQueries({ queryKey: KEYS.detail(id) });
        onAllDone?.();
      };

      // Temporal: poll workflow status
      const workflowIds = data.workflow_ids;
      if (engine === 'temporal' && workflowIds?.length) {
        const deadline = Date.now() + POLL_TIMEOUT_MS;
        pollTimerRef.current = setInterval(async () => {
          if (Date.now() > deadline) {
            clearPollTimer();
            await resetToIdle();
            return;
          }
          try {
            const res = await workflowsApi.listForCampaign(id);
            const allTerminal =
              res.workflows.length >= workflowIds.length &&
              res.workflows.every((w) => TERMINAL_STATUSES.includes(w.status));
            if (allTerminal) {
              clearPollTimer();
              await resetToIdle();
            }
          } catch {
            /* ignore */
          }
        }, POLL_INTERVAL_MS);
        return;
      }

      // In-process TaskQueue: poll tasks
      const taskIds = data.task_ids;
      if (taskIds?.length) {
        const deadline = Date.now() + POLL_TIMEOUT_MS;
        pollTimerRef.current = setInterval(async () => {
          if (Date.now() > deadline) {
            clearPollTimer();
            await resetToIdle();
            return;
          }
          try {
            const tasks = await tasksApi.list(taskIds);
            const allTerminal =
              tasks.length >= taskIds.length &&
              tasks.every((task) => TERMINAL_STATUSES.includes(task.status));
            if (allTerminal) {
              clearPollTimer();
              await resetToIdle();
            }
          } catch {
            /* ignore */
          }
        }, POLL_INTERVAL_MS);
        return;
      }

      await resetToIdle();
    }
  });
}

/** Epic 04 entity dispatch — FSM drives status; do not reset to idle. */
export function useDispatchCampaign(
  onAllDone?: (summary?: DispatchResultSummary) => void
) {
  const qc = useQueryClient();
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearPollTimer = () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  };

  useEffect(() => clearPollTimer, []);

  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: CampaignDispatchIn }) =>
      campaignsApi.dispatch(id, body),
    onSuccess: async (data, { id }) => {
      clearPollTimer();
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(id) });
      qc.invalidateQueries({ queryKey: ['executions'] });
      qc.invalidateQueries({ queryKey: KEYS.executionRuntime });

      const summary = summarizeDispatchResult(data);
      if (summary.allTerminal) {
        onAllDone?.(summary);
        return;
      }

      const deadline = Date.now() + POLL_TIMEOUT_MS;
      pollTimerRef.current = setInterval(async () => {
        if (Date.now() > deadline) {
          clearPollTimer();
          onAllDone?.();
          return;
        }
        try {
          const camp = await campaignsApi.get(id);
          if (isCampaignTerminal(camp.status)) {
            clearPollTimer();
            qc.invalidateQueries({ queryKey: KEYS.list });
            qc.invalidateQueries({ queryKey: KEYS.detail(id) });
            onAllDone?.();
          }
        } catch {
          /* ignore */
        }
      }, POLL_INTERVAL_MS);
    }
  });
}
