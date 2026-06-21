'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { executionsApi, workflowsApi } from '../services/api';
import {
  countActiveExecutions,
  countActiveWorkflows,
  isCampaignDrainComplete
} from '../lib/campaign-workflow-status';

export type CampaignStopDrainState = {
  startedAt: number;
  workflowsSignalled?: number;
  /** Toast when workflows + executions are fully terminal. */
  notifyOnComplete?: boolean;
};

export const campaignStopDrainKey = (campaignId: string) =>
  ['campaign-stop-drain', campaignId] as const;

const DRAIN_POLL_MS = 2_000;
const DRAIN_TIMEOUT_MS = 10 * 60 * 1000;
const DRAIN_RECOVERY_STALE_MS = 30_000;

export function markCampaignStopDrain(
  qc: ReturnType<typeof useQueryClient>,
  campaignId: string,
  opts?: { workflowsSignalled?: number; notifyOnComplete?: boolean }
) {
  qc.setQueryData<CampaignStopDrainState>(campaignStopDrainKey(campaignId), {
    startedAt: Date.now(),
    workflowsSignalled: opts?.workflowsSignalled,
    notifyOnComplete: opts?.notifyOnComplete ?? false
  });
}

export function clearCampaignStopDrain(
  qc: ReturnType<typeof useQueryClient>,
  campaignId: string
) {
  qc.removeQueries({ queryKey: campaignStopDrainKey(campaignId) });
}

async function fetchDrainSnapshot(campaignId: string) {
  const [wfRes, exRes] = await Promise.all([
    workflowsApi.listForCampaign(campaignId),
    executionsApi.list({ campaignId, limit: 200 })
  ]);
  const activeWorkflows = countActiveWorkflows(wfRes.workflows);
  const activeExecutions = countActiveExecutions(exRes.items);
  return { activeWorkflows, activeExecutions };
}

export function shouldProbeCancelledDrain(
  campaignId: string,
  campaignStatus: string | undefined,
  explicitDrain: boolean
): boolean {
  return Boolean(campaignId) && campaignStatus === 'cancelled' && !explicitDrain;
}

/**
 * Tracks cooperative cancel drain: API marks campaign cancelled immediately,
 * but Temporal workflows / executions may still finish the current step.
 */
export function useCampaignStopDrain(
  campaignId: string,
  campaignStatus?: string
) {
  const qc = useQueryClient();
  const t = useTranslations('campaignsFeature.list');
  const completedNotifiedRef = useRef(false);
  const sawActiveRef = useRef(false);

  const drainState = qc.getQueryData<CampaignStopDrainState>(
    campaignStopDrainKey(campaignId)
  );
  const explicitDrain = Boolean(drainState);

  // Recover mid-drain after refresh: cancelled in DB but workflows still active.
  // This uses a shared query key so StatusBadge + RowActions + Progress do not
  // each fire their own workflows/executions probe for the same campaign row.
  const { data: recoverySnapshot } = useQuery({
    queryKey: ['campaign-stop-drain-recovery', campaignId],
    queryFn: () => fetchDrainSnapshot(campaignId),
    enabled: shouldProbeCancelledDrain(campaignId, campaignStatus, explicitDrain),
    staleTime: DRAIN_RECOVERY_STALE_MS,
    refetchOnWindowFocus: false,
    refetchInterval: false,
    retry: false
  });

  useEffect(() => {
    if (
      !shouldProbeCancelledDrain(campaignId, campaignStatus, explicitDrain) ||
      !recoverySnapshot ||
      isCampaignDrainComplete(recoverySnapshot)
    ) {
      return;
    }
    markCampaignStopDrain(qc, campaignId);
  }, [campaignId, campaignStatus, explicitDrain, qc, recoverySnapshot]);

  const { data: snapshot } = useQuery({
    queryKey: ['campaign-stop-drain-snapshot', campaignId],
    queryFn: () => fetchDrainSnapshot(campaignId),
    enabled: Boolean(campaignId) && explicitDrain,
    refetchInterval: (query) => {
      if (!explicitDrain) return false;
      const startedAt =
        qc.getQueryData<CampaignStopDrainState>(campaignStopDrainKey(campaignId))
          ?.startedAt ?? 0;
      if (startedAt && Date.now() - startedAt > DRAIN_TIMEOUT_MS) {
        return false;
      }
      const data = query.state.data;
      if (data && isCampaignDrainComplete(data)) {
        return false;
      }
      return DRAIN_POLL_MS;
    },
    staleTime: 0
  });

  const activeWorkflowCount = snapshot?.activeWorkflows ?? 0;
  const activeExecutionCount = snapshot?.activeExecutions ?? 0;

  useEffect(() => {
    if (activeWorkflowCount + activeExecutionCount > 0) {
      sawActiveRef.current = true;
    }
  }, [activeWorkflowCount, activeExecutionCount]);
  const drainComplete =
    explicitDrain &&
    snapshot != null &&
    isCampaignDrainComplete(snapshot);
  const isStopping =
    explicitDrain &&
    !drainComplete &&
    (snapshot == null ||
      activeWorkflowCount + activeExecutionCount > 0);
  const isDraining = explicitDrain && !drainComplete;

  useEffect(() => {
    if (!drainComplete || !explicitDrain || completedNotifiedRef.current) return;
    completedNotifiedRef.current = true;

    const state = qc.getQueryData<CampaignStopDrainState>(
      campaignStopDrainKey(campaignId)
    );
    clearCampaignStopDrain(qc, campaignId);
    qc.invalidateQueries({ queryKey: ['campaigns'] });
    qc.invalidateQueries({ queryKey: ['campaigns', campaignId] });
    qc.invalidateQueries({ queryKey: ['campaign-workflows', campaignId] });
    qc.invalidateQueries({ queryKey: ['campaign-executions', campaignId] });

    if (
      state?.notifyOnComplete &&
      (sawActiveRef.current || (state.workflowsSignalled ?? 0) > 0)
    ) {
      toast.success(t('stopComplete'));
    }
  }, [campaignId, drainComplete, explicitDrain, qc, t]);

  useEffect(() => {
    if (!explicitDrain) {
      completedNotifiedRef.current = false;
      sawActiveRef.current = false;
    }
  }, [explicitDrain, campaignId]);

  return {
    isDraining,
    isStopping,
    activeWorkflowCount,
    activeExecutionCount
  };
}
