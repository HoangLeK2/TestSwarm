import type { Device } from '../types';
import type { DeviceOut } from '../services/manage-api';

const OFFLINE_DEVICE_STATES = new Set(['DISCONNECTED', 'DEAD']);

type DeviceWithLiveTransport = Device & {
  agent_connected?: boolean;
  stf_connected?: boolean;
};

function normalizeDeviceFarmState(state: string | null | undefined): string {
  return String(state || '')
    .replace('DeviceState.', '')
    .trim()
    .toUpperCase();
}

function hasLiveTransportEvidence(device: DeviceWithLiveTransport): boolean {
  const touchMethod = String(device.touch_method || '')
    .trim()
    .toLowerCase();
  return Boolean(
    device.agent_connected ||
      device.u2_ready ||
      device.minitouch_ready ||
      device.stf_connected ||
      (touchMethod && touchMethod !== 'none')
  );
}

function hasStrongLiveTransportEvidence(
  device: DeviceWithLiveTransport
): boolean {
  return Boolean(device.agent_connected || device.stf_connected);
}

function hasRunningWorkEvidence(device: DeviceWithLiveTransport): boolean {
  const usageState = String(device.usage_state || 'idle')
    .trim()
    .toLowerCase();
  return Number(device.scenario_active || 0) > 0 || usageState !== 'idle';
}

export function isVisibleDeviceFarmActiveDevice(device: Device): boolean {
  const state = normalizeDeviceFarmState(device.state);
  if (hasRunningWorkEvidence(device)) return true;
  if (OFFLINE_DEVICE_STATES.has(state)) {
    return hasStrongLiveTransportEvidence(device);
  }
  if (hasLiveTransportEvidence(device)) return true;
  return Boolean(state) && !OFFLINE_DEVICE_STATES.has(state);
}

export function filterVisibleDeviceFarmDevices(
  devices: Device[],
  registeredDevices: DeviceOut[]
): Device[] {
  if (registeredDevices.length === 0) return devices;

  const registeredSerials = new Set(registeredDevices.map((d) => d.serial));

  return devices.filter((device) => {
    const registeredSerial = device.registered_serial ?? device.serial;
    if (!registeredSerials.has(registeredSerial)) return false;
    return true;
  });
}

export function filterDeviceFarmActiveGridDevices(devices: Device[]): Device[] {
  return devices.filter((device) => {
    if (device.health) {
      return (
        device.health.agent.status !== 'offline' &&
        device.health.command.status !== 'unavailable'
      );
    }
    return (
      isVisibleDeviceFarmActiveDevice(device) && hasLiveTransportEvidence(device)
    );
  });
}
