'use client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { campaignsApi, scenariosApi, tasksApi, workflowsApi } from '../services/api';
import type {
  CampaignCreate,
  CampaignOut,
  CampaignRunResponse,
  CampaignStatus,
  ScenarioCreate,
  ScenarioUpdate
} from '../types';
import { fleetRun, fleetStatus, type FleetStatusResult } from '../../devices/services/api';

const KEYS = {
  list: ['campaigns'] as const,
  detail: (id: string) => ['campaigns', id] as const,
  devices: (id: string) => ['campaigns', id, 'devices'] as const,
  scenarios: (campaignId: string) => ['campaigns', campaignId, 'scenarios'] as const,
};

export function useCampaigns() {
  return useQuery({
    queryKey: KEYS.list,
    queryFn: campaignsApi.list,
    refetchInterval: (query) => {
      const data = query.state.data as CampaignOut[] | undefined;
      return data && data.some((c: CampaignOut) => c.status === 'running') ? 3000 : false;
    }
  });
}

export function useCampaign(id: string) {
  return useQuery({
    queryKey: KEYS.detail(id),
    queryFn: () => campaignsApi.get(id),
    enabled: !!id
  });
}

export function useCampaignDevices(campaignId: string) {
  return useQuery({
    queryKey: KEYS.devices(campaignId),
    queryFn: () => campaignsApi.getDevices(campaignId),
    enabled: !!campaignId
  });
}

export function useAddDeviceToCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ campaignId, deviceId }: { campaignId: string; deviceId: string }) =>
      campaignsApi.addDevice(campaignId, deviceId),
    onSuccess: (_, { campaignId }) => {
      qc.invalidateQueries({ queryKey: KEYS.devices(campaignId) });
      qc.invalidateQueries({ queryKey: KEYS.list });
    }
  });
}

export function useRemoveDeviceFromCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ campaignId, deviceId }: { campaignId: string; deviceId: string }) =>
      campaignsApi.removeDevice(campaignId, deviceId),
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
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list })
  });
}

export function useUpdateCampaignStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: CampaignStatus }) =>
      campaignsApi.updateStatus(id, status),
    onSuccess: async (_data, { id }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(id) });
      await Promise.all([
        qc.refetchQueries({ queryKey: KEYS.list }),
        qc.refetchQueries({ queryKey: KEYS.detail(id) })
      ]);
    }
  });
}

export function useDeleteCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => campaignsApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.list });
    }
  });
}

export function useUpdateCampaignScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, scenario }: { id: string; scenario: Record<string, any> }) =>
      campaignsApi.updateScenario(id, scenario),
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
    refetchInterval: 2000,
    select: (tasks) => {
      const total = tasks.length;
      const done = tasks.filter((t) => t.status === 'DONE').length;
      const failed = tasks.filter((t) => t.status === 'FAILED').length;
      const running = tasks.filter((t) => t.status === 'RUNNING').length;
      const pending = tasks.filter((t) => t.status === 'PENDING').length;
      const terminal = done + failed;
      return { total, done, failed, running, pending, pct: total ? Math.round((terminal / total) * 100) : 0 };
    },
  });
}

// ── Scenario hooks ────────────────────────────────────────────────────────────

export function useScenarios(campaignId: string) {
  return useQuery({
    queryKey: KEYS.scenarios(campaignId),
    queryFn: () => scenariosApi.list(campaignId),
    enabled: !!campaignId,
  });
}

export function useCreateScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ campaignId, data }: { campaignId: string; data: ScenarioCreate }) =>
      scenariosApi.create(campaignId, data),
    onSuccess: (_, { campaignId }) => {
      qc.invalidateQueries({ queryKey: KEYS.scenarios(campaignId) });
      qc.invalidateQueries({ queryKey: KEYS.list });
    },
  });
}

export function useUpdateScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ campaignId, scenarioId, data }: { campaignId: string; scenarioId: string; data: ScenarioUpdate }) =>
      scenariosApi.update(campaignId, scenarioId, data),
    onSuccess: (_, { campaignId }) => {
      qc.invalidateQueries({ queryKey: KEYS.scenarios(campaignId) });
      qc.invalidateQueries({ queryKey: KEYS.list });
    },
  });
}

export function useDeleteScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ campaignId, scenarioId }: { campaignId: string; scenarioId: string }) =>
      scenariosApi.delete(campaignId, scenarioId),
    onSuccess: (_, { campaignId }) => {
      qc.invalidateQueries({ queryKey: KEYS.scenarios(campaignId) });
      qc.invalidateQueries({ queryKey: KEYS.list });
    },
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
        deviceContext: params.deviceContext,
      }),
    onSuccess: (_, { campaignId }) => {
      qc.invalidateQueries({ queryKey: KEYS.scenarios(campaignId) });
      qc.invalidateQueries({ queryKey: KEYS.list });
    },
  });
}

// ── Temporal Workflow hooks ──────────────────────────────────────────────────

export function useCampaignWorkflows(campaignId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['campaign-workflows', campaignId],
    queryFn: () => workflowsApi.listForCampaign(campaignId),
    enabled,
    refetchInterval: 3000,
  });
}

export function useWorkflowProgress(workflowId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['workflow-progress', workflowId],
    queryFn: () => workflowsApi.progress(workflowId),
    enabled: enabled && !!workflowId,
    refetchInterval: 2000,
  });
}

export function useWorkflowPause() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (workflowId: string) => workflowsApi.pause(workflowId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-workflows'] });
    },
  });
}

export function useWorkflowResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (workflowId: string) => workflowsApi.resume(workflowId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-workflows'] });
    },
  });
}

export function useWorkflowCancel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (workflowId: string) => workflowsApi.cancel(workflowId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-workflows'] });
    },
  });
}

// ── Fleet run ─────────────────────────────────────────────────────────────────

/** Fleet run: dispatch campaign scenario to ALL READY devices. */
export function useFleetRunCampaign(onDone?: (result: FleetStatusResult) => void) {
  const mutation = useMutation({
    mutationFn: (campaign: CampaignOut) => {
      // Try new scenarios[], else fall back to legacy scenario field
      const scenarios = campaign.scenarios ?? [];
      const steps = scenarios.length
        ? scenarios.flatMap((s) => s.steps)
        : campaign.scenario?.steps;
      if (!Array.isArray(steps) || !steps.length) {
        return Promise.reject(new Error('Campaign chưa có kịch bản (steps). Hãy thiết lập kịch bản trước.'));
      }
      return fleetRun(steps as Array<Record<string, unknown>>);
    },
    onSuccess: (data) => {
      const deadline = Date.now() + 10 * 60 * 1000;
      const t = setInterval(async () => {
        if (Date.now() > deadline) { clearInterval(t); return; }
        try {
          const s = await fleetStatus(data.run_id);
          if (s.all_complete) { clearInterval(t); onDone?.(s); }
        } catch { /* ignore */ }
      }, 3000);
    },
  });
  return mutation;
}

const TERMINAL_STATUSES = ['DONE', 'FAILED', 'COMPLETED', 'CANCELLED', 'TERMINATED'];
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 10 * 60 * 1000;

const _engineStorageKey = (campaignId: string) => `df_campaign_engine:${campaignId}`;

export type RunCampaignOptions = {
  onTemporalFallback?: () => void;
};

export function useRunCampaign(onAllDone?: () => void, options?: RunCampaignOptions) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => campaignsApi.run(id),
    onSuccess: (data: CampaignRunResponse, id) => {
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

      // Temporal: poll workflow status
      const workflowIds = data.workflow_ids;
      if (engine === 'temporal' && workflowIds?.length) {
        const deadline = Date.now() + POLL_TIMEOUT_MS;
        const timer = setInterval(async () => {
          if (Date.now() > deadline) { clearInterval(timer); onAllDone?.(); return; }
          try {
            const res = await workflowsApi.listForCampaign(id);
            const allTerminal = res.workflows.length >= workflowIds.length &&
              res.workflows.every((w) => TERMINAL_STATUSES.includes(w.status));
            if (allTerminal) {
              clearInterval(timer);
              qc.invalidateQueries({ queryKey: KEYS.list });
              qc.invalidateQueries({ queryKey: KEYS.detail(id) });
              onAllDone?.();
            }
          } catch { /* ignore */ }
        }, POLL_INTERVAL_MS);
        return;
      }

      // In-process TaskQueue: poll tasks
      const taskIds = data.task_ids;
      if (taskIds?.length) {
        const deadline = Date.now() + POLL_TIMEOUT_MS;
        const timer = setInterval(async () => {
          if (Date.now() > deadline) { clearInterval(timer); onAllDone?.(); return; }
          try {
            const tasks = await tasksApi.list(taskIds);
            const allTerminal = tasks.length >= taskIds.length &&
              tasks.every((task) => TERMINAL_STATUSES.includes(task.status));
            if (allTerminal) {
              clearInterval(timer);
              qc.invalidateQueries({ queryKey: KEYS.list });
              qc.invalidateQueries({ queryKey: KEYS.detail(id) });
              onAllDone?.();
            }
          } catch { /* ignore */ }
        }, POLL_INTERVAL_MS);
        return;
      }

      onAllDone?.();
    }
  });
}
