import type { Device } from '../types';

const OFFLINE_DEVICE_STATES = new Set(['DISCONNECTED', 'DEAD']);

function normalizeState(state: string | null | undefined): string {
  return String(state || '')
    .replace('DeviceState.', '')
    .trim()
    .toUpperCase();
}

function deviceKeys(device: Device): string[] {
  return [device.serial, device.registered_serial]
    .filter((key): key is string => Boolean(key && key.trim()))
    .map((key) => key.trim().toLowerCase());
}

function hasSharedDeviceKey(left: Device, right: Device): boolean {
  const rightKeys = new Set(deviceKeys(right));
  return deviceKeys(left).some((key) => rightKeys.has(key));
}

function isExplicitlyOffline(device: Device): boolean {
  return OFFLINE_DEVICE_STATES.has(normalizeState(device.state));
}

function positiveDimension(value: number | undefined): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
    ? value
    : undefined;
}

function mergeLiveDevice(previous: Device | undefined, live: Device): Device {
  if (!previous) return live;
  return {
    ...previous,
    ...live,
    screen_width: positiveDimension(live.screen_width) ?? previous.screen_width,
    screen_height:
      positiveDimension(live.screen_height) ?? previous.screen_height,
    manual_takeover_active:
      live.manual_takeover_active ?? previous.manual_takeover_active,
    scenario_active: live.scenario_active ?? previous.scenario_active
  };
}

export function mergeLiveDeviceSnapshot(
  previousDevices: Device[],
  liveDevices: Device[],
  options: { dropStaleOnEmpty?: boolean } = {}
): Device[] {
  if (liveDevices.length === 0) {
    // An empty feed is not evidence of offline by itself — but when agent-boot
    // stops, the live endpoint can no longer map the stale runtime serial back
    // to a registered device, so it drops the row instead of reporting it
    // DISCONNECTED. Without this the last READY snapshot stays painted forever.
    if (options.dropStaleOnEmpty) return [];
    return previousDevices.filter((device) => !isExplicitlyOffline(device));
  }

  const merged = liveDevices.map((live) =>
    mergeLiveDevice(
      previousDevices.find((previous) => hasSharedDeviceKey(previous, live)),
      live
    )
  );

  return merged;
}
