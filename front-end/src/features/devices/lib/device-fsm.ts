/** Control-plane device FSM — mirrors backend (DF-T-02-002). */
import type { DeviceOut } from '../services/manage-api';

const PENDING_SERIAL_PREFIX = 'pending-';

function isPendingSerial(serial: string): boolean {
  return serial.startsWith(PENDING_SERIAL_PREFIX);
}

export const DEVICE_FSM_STATES = [
  'unknown',
  'connecting',
  'online',
  'busy',
  'reconnecting',
  'dead'
] as const;

export type DeviceFsmStateKey = (typeof DEVICE_FSM_STATES)[number];

export type DeviceFsmFilterKey =
  | 'all'
  | DeviceFsmStateKey
  | 'transport_online'
  | 'transport_offline';

export const DEVICE_FSM_BADGE_VARIANT: Record<
  DeviceFsmStateKey,
  'default' | 'secondary' | 'outline' | 'destructive'
> = {
  unknown: 'outline',
  connecting: 'secondary',
  online: 'default',
  busy: 'secondary',
  reconnecting: 'outline',
  dead: 'destructive'
};

/** Extra Tailwind classes for FSM badge emphasis. */
export const DEVICE_FSM_BADGE_CLASS: Partial<
  Record<DeviceFsmStateKey, string>
> = {
  reconnecting:
    'animate-pulse border-amber-500/50 text-amber-700 dark:text-amber-400'
};

export function normalizeDeviceFsmState(
  state: string | null | undefined
): DeviceFsmStateKey {
  const raw = (state || 'unknown').trim().toLowerCase();
  if ((DEVICE_FSM_STATES as readonly string[]).includes(raw)) {
    return raw as DeviceFsmStateKey;
  }
  return 'unknown';
}

export function deviceFsmStateOf(device: Pick<DeviceOut, 'state' | 'serial'>) {
  if (isPendingSerial(device.serial)) return 'unknown' as DeviceFsmStateKey;
  return normalizeDeviceFsmState(device.state);
}

export function matchesDeviceFsmFilter(
  device: DeviceOut,
  filter: DeviceFsmFilterKey,
  isTransportOnline: (d: DeviceOut) => boolean
): boolean {
  if (filter === 'all') return true;
  if (filter === 'transport_online') return isTransportOnline(device);
  if (filter === 'transport_offline') return !isTransportOnline(device);
  return deviceFsmStateOf(device) === filter;
}

/** States where dispatch/claim may succeed (control plane). */
export function isDeviceFsmDispatchable(state: DeviceFsmStateKey): boolean {
  return state === 'online';
}
