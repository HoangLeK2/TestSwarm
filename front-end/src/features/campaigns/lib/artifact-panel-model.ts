import type { ExecutionArtifact, ExecutionOut } from '../types';

export type DeviceFilter = 'all' | string;

export type ResolvedMonitorArtifact = {
  key: string;
  artifact: ExecutionArtifact;
  href: string;
  deviceLabel: string;
  subtitle: string;
  isFail: boolean;
  stepNumber: number | null;
  timeLabel: string;
};

export type ArtifactDeviceGroup = {
  device: string;
  shots: ResolvedMonitorArtifact[];
};

export function artifactIsFailShot(artifact: ExecutionArtifact): boolean {
  if (artifact.artifact_type === 'fail.screenshot') return true;
  if (artifact.ok === false) return true;
  return artifact.artifact_type.includes('fail');
}

export function uniqueDeviceSerials(
  items: ResolvedMonitorArtifact[]
): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of items) {
    const serial = item.deviceLabel.trim();
    if (!serial || seen.has(serial)) continue;
    seen.add(serial);
    out.push(serial);
  }
  return out;
}

export function filterArtifactsByDevice(
  items: ResolvedMonitorArtifact[],
  deviceFilter: DeviceFilter
): ResolvedMonitorArtifact[] {
  if (deviceFilter === 'all') return items;
  return items.filter((item) => item.deviceLabel === deviceFilter);
}

export function groupArtifactsByDevice(
  items: ResolvedMonitorArtifact[],
  deviceFilter: DeviceFilter
): ArtifactDeviceGroup[] {
  const filtered = filterArtifactsByDevice(items, deviceFilter);
  const order: string[] = [];
  const map = new Map<string, ResolvedMonitorArtifact[]>();

  for (const item of filtered) {
    if (!map.has(item.deviceLabel)) {
      map.set(item.deviceLabel, []);
      order.push(item.deviceLabel);
    }
    map.get(item.deviceLabel)!.push(item);
  }

  return order.map((device) => ({
    device,
    shots: map.get(device) ?? []
  }));
}

export function executionRunLabel(
  execution: ExecutionOut,
  statusLabel: (status: string) => string
): string {
  const when =
    execution.finished_at ?? execution.started_at ?? execution.created_at;
  const date = when ? new Date(when) : null;
  const whenLabel =
    date && !Number.isNaN(date.getTime())
      ? date.toLocaleString()
      : (when ?? '—');
  return `${whenLabel} · ${statusLabel(execution.status)}`;
}

export function neighborArtifactKeys(
  items: ResolvedMonitorArtifact[],
  currentKey: string | null
): { prev: string | null; next: string | null } {
  if (!currentKey) return { prev: null, next: null };
  const index = items.findIndex((item) => item.key === currentKey);
  if (index < 0) return { prev: null, next: null };
  return {
    prev: index > 0 ? items[index - 1]!.key : null,
    next: index < items.length - 1 ? items[index + 1]!.key : null
  };
}

export function sortExecutionsForArtifactPanel(
  executions: ExecutionOut[],
  shotCounts: Map<string, number>
): ExecutionOut[] {
  return [...executions].sort((a, b) => {
    const aShots = shotCounts.get(a.id) ?? 0;
    const bShots = shotCounts.get(b.id) ?? 0;
    if (aShots > 0 && bShots === 0) return -1;
    if (aShots === 0 && bShots > 0) return 1;
    const aTime = Date.parse(
      a.finished_at ?? a.started_at ?? a.created_at ?? ''
    );
    const bTime = Date.parse(
      b.finished_at ?? b.started_at ?? b.created_at ?? ''
    );
    return (
      (Number.isNaN(bTime) ? 0 : bTime) - (Number.isNaN(aTime) ? 0 : aTime)
    );
  });
}

export function pickDefaultExecutionId(
  executions: ExecutionOut[],
  shotCounts: Map<string, number>,
  currentId: string | null
): string | null {
  if (!executions.length) return null;
  if (currentId && executions.some((execution) => execution.id === currentId)) {
    return currentId;
  }
  const withShots = executions.find(
    (execution) => (shotCounts.get(execution.id) ?? 0) > 0
  );
  return withShots?.id ?? executions[0]!.id;
}

export function filterExecutionsWithShots(
  executions: ExecutionOut[],
  shotCounts: Map<string, number>,
  onlyWithShots: boolean
): ExecutionOut[] {
  if (!onlyWithShots) return executions;
  return executions.filter(
    (execution) => (shotCounts.get(execution.id) ?? 0) > 0
  );
}
