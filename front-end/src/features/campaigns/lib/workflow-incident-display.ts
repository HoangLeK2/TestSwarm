import type { ExecutionEventOut } from '../../device-farm/services/generated/DeviceFarmApi';
import type { IncidentEvent } from '../types';

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function looksLikeUuid(value: string): boolean {
  return UUID_RE.test(value.trim());
}

export function shortDisplayId(id?: string | null): string {
  return id ? id.slice(0, 8) : '';
}

export function isRecoveryIncidentEvent(eventType: string): boolean {
  return (
    eventType === 'incident.recovery.started' ||
    eventType === 'incident.recovery.completed' ||
    eventType === 'incident.resolved' ||
    eventType === 'incident.failed'
  );
}

export function incidentEventLabelKey(eventType: string): string {
  if (eventType === 'incident.detected') return 'monitorIncidentDetected';
  if (eventType === 'incident.recovery.started')
    return 'monitorIncidentRecoveryStarted';
  if (eventType === 'incident.recovery.completed')
    return 'monitorIncidentRecoveryCompleted';
  if (eventType === 'incident.resolved') return 'monitorIncidentResolved';
  if (eventType === 'incident.failed') return 'monitorIncidentFailed';
  return 'monitorIncidentEvent';
}

export function resolveRecoveryScenarioName(
  incident: IncidentEvent,
  namesById: ReadonlyMap<string, string>
): string {
  const rawName = incident.recovery_scenario_name?.trim() ?? '';
  if (rawName && !looksLikeUuid(rawName)) return rawName;

  const scenarioId =
    incident.recovery_scenario_id?.trim() || incident.scenario_id?.trim() || '';
  if (scenarioId && namesById.has(scenarioId)) {
    return namesById.get(scenarioId) ?? '';
  }
  if (rawName) return rawName;
  if (scenarioId) return shortDisplayId(scenarioId);
  return '';
}

export type ActiveRecoveryState = {
  active: boolean;
  scenarioName?: string;
  scenarioId?: string;
};

export function detectActiveRecoveryFromEvents(
  events: ExecutionEventOut[],
  namesById: ReadonlyMap<string, string> = new Map()
): ActiveRecoveryState {
  let active = false;
  let scenarioName: string | undefined;
  let scenarioId: string | undefined;

  for (const ev of events) {
    const p = (ev.payload ?? {}) as Record<string, unknown>;
    if (ev.event_type === 'incident.recovery.started') {
      active = true;
      scenarioId =
        typeof p.recovery_scenario_id === 'string'
          ? p.recovery_scenario_id
          : typeof p.scenario_id === 'string'
            ? p.scenario_id
            : undefined;
      const rawName =
        typeof p.recovery_scenario_name === 'string'
          ? p.recovery_scenario_name
          : '';
      scenarioName =
        resolveRecoveryScenarioName(
          {
            event_type: ev.event_type,
            recovery_scenario_name: rawName,
            recovery_scenario_id: scenarioId ?? null,
            scenario_id: scenarioId ?? null
          },
          namesById
        ) || undefined;
      continue;
    }
    if (
      ev.event_type === 'incident.recovery.completed' ||
      ev.event_type === 'incident.resolved' ||
      ev.event_type === 'incident.failed'
    ) {
      active = false;
      scenarioName = undefined;
      scenarioId = undefined;
    }
  }

  return { active, scenarioName, scenarioId };
}
