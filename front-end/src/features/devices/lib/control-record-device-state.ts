import type { Device } from '../types';

const CONTROL_RECORD_CONNECTED_STATES = new Set(['READY', 'ONLINE', 'BUSY']);
const CONTROL_RECORD_TERMINAL_STATES = new Set(['DEAD']);

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
  previousConnectedDevices: Device[] = [],
  options?: {
    preserveTerminalSerials?: ReadonlySet<string>;
  }
): Device[] {
  const connected = devices.filter(isControlRecordConnectedDevice);
  if (previousConnectedDevices.length === 0) return connected;

  const connectedBySerial = new Map(
    connected.map((device) => [device.serial, device])
  );
  const terminalSerials = new Set(
    devices
      .filter((device) =>
        CONTROL_RECORD_TERMINAL_STATES.has(
          normalizeControlRecordDeviceState(device.state)
        )
      )
      .map((device) => device.serial)
  );
  const resolved = previousConnectedDevices.flatMap((previous) => {
    const current = connectedBySerial.get(previous.serial);
    if (current) {
      connectedBySerial.delete(previous.serial);
      return [current];
    }
    return terminalSerials.has(previous.serial) &&
      !options?.preserveTerminalSerials?.has(previous.serial)
      ? []
      : [previous];
  });

  return [...resolved, ...Array.from(connectedBySerial.values())];
}

export function resolveControlRecordSelectedDevice(
  connectedDevices: Device[],
  selectedSerial: string | null | undefined
): Device | null {
  const explicitSerial = (selectedSerial ?? '').trim();
  if (explicitSerial) {
    return (
      connectedDevices.find((device) => device.serial === explicitSerial) ?? null
    );
  }
  return connectedDevices[0] ?? null;
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
