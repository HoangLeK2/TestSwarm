'use client';

import { useMemo } from 'react';
import { useOrgScenarios } from '@/features/org-scenarios/hooks/use-org-scenarios';
import { deviceSerialFromWorkflowId } from '../lib/execution-event-utils';
import { detectActiveRecoveryFromEvents } from '../lib/workflow-incident-display';
import { useExecutionEventStream } from '../hooks/use-execution-event-stream';
import type { WorkflowInfo } from '../types';

export function useWorkflowRecoveryState(
  wf: WorkflowInfo,
  options?: { enabled?: boolean }
) {
  const enabled = options?.enabled ?? true;
  const isActive = wf.status === 'RUNNING' || wf.status === 'PAUSED';
  const executionId = wf.execution_id ?? undefined;
  const deviceSerial =
    wf.device_serial || deviceSerialFromWorkflowId(wf.workflow_id) || '';
  const { data: orgScenarios } = useOrgScenarios();
  const scenarioNamesById = useMemo(() => {
    const map = new Map<string, string>();
    for (const scenario of orgScenarios ?? []) {
      map.set(scenario.id, scenario.name);
    }
    return map;
  }, [orgScenarios]);

  const eventStream = useExecutionEventStream(executionId, {
    enabled: enabled && isActive && !!executionId,
    workflowId: wf.workflow_id,
    deviceSerial
  });

  const activeRecovery = useMemo(
    () => detectActiveRecoveryFromEvents(eventStream.events, scenarioNamesById),
    [eventStream.events, scenarioNamesById]
  );

  const isRecoveryMode =
    wf.workflow_kind === 'recovery' || activeRecovery.active;

  return {
    isRecoveryMode,
    recoveryScenarioName: activeRecovery.scenarioName,
    eventStream
  };
}
