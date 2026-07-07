import type { Device } from '../types';

const CONTROL_RECORD_CONNECTED_STATES = new Set(['READY', 'ONLINE', 'BUSY']);
const CONTROL_RECORD_OFFLINE_STATES = new Set(['DISCONNECTED', 'DEAD']);

export function normalizeControlRecordDeviceState(
  state: string | null | undefined
) {
  return String(state || '')
    .replace('DeviceState.', '')
    .trim()
    .toUpperCase();
}

export function isControlRecordConnectedDevice(
  device: Pick<
    Device,
    'state' | 'touch_method' | 'minitouch_ready' | 'u2_ready'
  >
): boolean {
  const state = normalizeControlRecordDeviceState(device.state);
  if (CONTROL_RECORD_CONNECTED_STATES.has(state)) return true;
  if (state === 'DISCONNECTED' || state === 'DEAD') return false;

  const touchMethod = String(device.touch_method || '')
    .trim()
    .toLowerCase();
  return Boolean(
    device.u2_ready ||
      device.minitouch_ready ||
      (touchMethod && touchMethod !== 'none')
  );
}

export function resolveControlRecordConnectedDevices(
  devices: Device[],
  previousConnectedDevices: Device[] = []
): Device[] {
  const connected = devices.filter(isControlRecordConnectedDevice);
  if (connected.length > 0) return connected;
  if (devices.length === 0) return previousConnectedDevices;
  if (previousConnectedDevices.length > 0) {
    const terminalOfflineSerials = new Set(
      devices
        .filter((device) =>
          CONTROL_RECORD_OFFLINE_STATES.has(
            normalizeControlRecordDeviceState(device.state)
          )
        )
        .map((device) => device.serial)
    );
    const stillPlausiblyLive = previousConnectedDevices.filter(
      (device) => !terminalOfflineSerials.has(device.serial)
    );
    if (stillPlausiblyLive.length > 0) return stillPlausiblyLive;
  }
  return [];
}

export function shouldShowControlRecordNoDeviceBanner(options: {
  devicesReady: boolean;
  connectedDeviceCount: number;
}): boolean {
  return options.devicesReady && options.connectedDeviceCount === 0;
}

export function resolveControlRecordHierarchySerial(
  selectedSerial: string | null | undefined,
  selectedDeviceSerial: string | null | undefined
): string | null {
  const explicit = (selectedSerial ?? '').trim();
  if (explicit) return explicit;
  const fromDevice = (selectedDeviceSerial ?? '').trim();
  return fromDevice || null;
}

export function deviceSerialMatches(a: string, b: string): boolean {
  const left = a.trim().toLowerCase();
  const right = b.trim().toLowerCase();
  if (!left || !right) return false;
  return left === right || left.endsWith(right) || right.endsWith(left);
}

export function isManualControlEligible(d: {
  state?: string | null;
  scenario_active?: number | null;
  manual_takeover_active?: boolean | null;
}) {
  const state = normalizeControlRecordDeviceState(d.state);
  return (
    state === 'READY' &&
    ((d.scenario_active ?? 0) <= 0 || Boolean(d.manual_takeover_active))
  );
}

export function isManualControlBlockedByAutomation(d: {
  state?: string | null;
  scenario_active?: number | null;
  manual_takeover_active?: boolean | null;
}) {
  if (Boolean(d.manual_takeover_active)) return false;
  const state = normalizeControlRecordDeviceState(d.state);
  return state === 'BUSY' || (d.scenario_active ?? 0) > 0;
}
