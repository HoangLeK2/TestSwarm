import type { Device } from '../types';
import { isVisibleDeviceFarmActiveDevice } from './device-farm-visible-devices';

export type DeviceFarmActivity = 'idle' | 'running' | 'manual' | 'unavailable';
export type DeviceFarmActivityFilter = 'all' | DeviceFarmActivity;

export const ALL_RUNS = 'all';

/**
 * What the phone is doing right now, in the operator's terms.
 *
 * Running work is checked before reachability on purpose: a phone whose agent
 * flaps mid-scenario is still a phone with a run on it, and hiding it under
 * "unavailable" is how a stuck run goes unnoticed.
 */
export function getDeviceFarmActivity(device: Device): DeviceFarmActivity {
  const usageState = String(device.usage_state || 'idle')
    .trim()
    .toLowerCase();
  if (
    Number(device.scenario_active || 0) > 0 ||
    device.active_run ||
    device.state?.toUpperCase() === 'BUSY' ||
    device.health?.command.status === 'busy'
  ) {
    return 'running';
  }
  if (device.manual_takeover_active || usageState !== 'idle') return 'manual';
  if (device.health) {
    return device.health.agent.status === 'offline' ||
      device.health.command.status === 'unavailable'
      ? 'unavailable'
      : 'idle';
  }
  return isVisibleDeviceFarmActiveDevice(device) ? 'idle' : 'unavailable';
}

/** Stable identity of the run on a device, for grouping the fleet by run. */
export function getDeviceFarmRunKey(device: Device): string | null {
  const run = device.active_run;
  if (!run) return null;
  return run.scenario_id || run.campaign_id || run.execution_id || null;
}

export function getDeviceFarmRunLabel(device: Device): string | null {
  const run = device.active_run;
  if (!run) return null;
  const key = getDeviceFarmRunKey(device);
  return (
    run.scenario_name ||
    run.campaign_name ||
    (key ? `#${key.slice(0, 8)}` : null)
  );
}

/** Runs present in the fleet right now, for the run filter options. */
export function listDeviceFarmRuns(
  devices: Device[]
): { key: string; label: string; count: number }[] {
  const runs = new Map<string, { key: string; label: string; count: number }>();
  for (const device of devices) {
    const key = getDeviceFarmRunKey(device);
    if (!key) continue;
    const existing = runs.get(key);
    if (existing) {
      existing.count += 1;
      continue;
    }
    runs.set(key, {
      key,
      label: getDeviceFarmRunLabel(device) ?? key,
      count: 1
    });
  }
  return Array.from(runs.values()).sort((a, b) =>
    a.label.localeCompare(b.label)
  );
}

function deviceHaystack(device: Device): string {
  return [
    device.serial,
    device.registered_serial,
    device.name,
    device.display_name,
    device.brand,
    device.model,
    `${device.brand ?? ''} ${device.model ?? ''}`,
    getDeviceFarmRunLabel(device)
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

export function filterDeviceFarmDevices(
  devices: Device[],
  {
    query,
    activity,
    runKey
  }: {
    query: string;
    activity: DeviceFarmActivityFilter;
    runKey: string;
  }
): Device[] {
  const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (tokens.length === 0 && activity === 'all' && runKey === ALL_RUNS) {
    return devices;
  }

  return devices.filter((device) => {
    if (activity !== 'all' && getDeviceFarmActivity(device) !== activity) {
      return false;
    }
    if (runKey !== ALL_RUNS && getDeviceFarmRunKey(device) !== runKey) {
      return false;
    }
    if (tokens.length === 0) return true;
    const haystack = deviceHaystack(device);
    return tokens.every((token) => haystack.includes(token));
  });
}
