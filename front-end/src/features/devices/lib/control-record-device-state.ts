import type { Device } from '../types';

const CONTROL_RECORD_CONNECTED_STATES = new Set(['READY', 'ONLINE', 'BUSY']);

export function normalizeControlRecordDeviceState(
  state: string | null | undefined
) {
  return String(state || '')
    .replace('DeviceState.', '')
    .trim()
    .toUpperCase();
}

export function isControlRecordConnectedDevice(
  device: Pick<Device, 'state'>
): boolean {
  return CONTROL_RECORD_CONNECTED_STATES.has(
    normalizeControlRecordDeviceState(device.state)
  );
}
