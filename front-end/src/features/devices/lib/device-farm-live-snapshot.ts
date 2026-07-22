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

function mergeLiveDevice(previous: Device | undefined, live: Device): Device {
  if (!previous) return live;
  return {
    ...previous,
    ...live,
    manual_takeover_active:
      live.manual_takeover_active ?? previous.manual_takeover_active,
    scenario_active: live.scenario_active ?? previous.scenario_active
  };
}

export function mergeLiveDeviceSnapshot(
  previousDevices: Device[],
  liveDevices: Device[]
): Device[] {
  if (liveDevices.length === 0) {
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
