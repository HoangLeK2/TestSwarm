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
  const touchMethod = String(device.touch_method || '').trim().toLowerCase();
  return Boolean(
    device.agent_connected ||
      device.u2_ready ||
      device.minitouch_ready ||
      device.stf_connected ||
      (touchMethod && touchMethod !== 'none')
  );
}

export function isVisibleDeviceFarmActiveDevice(device: Device): boolean {
  if (hasLiveTransportEvidence(device)) return true;
  const state = normalizeDeviceFarmState(device.state);
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
