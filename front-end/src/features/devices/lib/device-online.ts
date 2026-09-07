import type { DeviceOut, RelayAgentOut } from '../services/manage-api';
import {
  getRelayConnectionState,
  isRelayOperational
} from './relay-agent-status';

const LAST_SEEN_ONLINE_MS = 60_000;
const PENDING_SERIAL_PREFIX = 'pending-';

function isPendingDevice(device: { serial: string }): boolean {
  return device.serial.startsWith(PENDING_SERIAL_PREFIX);
}

function isRelayManagedDevice(device: DeviceOut): boolean {
  return Boolean(
    (device.adb_serial && device.adb_serial.trim()) ||
      (device.adb_ip && device.adb_ip.trim())
  );
}

/** Resolve the relay agent currently associated with a registered device. */
export function resolveDeviceRelay(
  device: DeviceOut,
  relayMap: Record<string, RelayAgentOut>
): RelayAgentOut | undefined {
  return (
    (device.relay_id ? relayMap[device.relay_id] : undefined) ??
    (device.managed_by_relay_id
      ? relayMap[device.managed_by_relay_id]
      : undefined) ??
    relayMap[device.serial] ??
    (device.relay_serial ? relayMap[device.relay_serial] : undefined) ??
    (device.adb_serial ? relayMap[device.adb_serial] : undefined) ??
    (device.adb_ip ? relayMap[device.adb_ip] : undefined)
  );
}

/**
 * List "online" matches backend dispatch: live relay transport OR recent DB heartbeat.
 */
export function isDeviceOnlineForList(
  device: DeviceOut,
  relayMap: Record<string, RelayAgentOut>,
  now = Date.now()
): boolean {
  if (isPendingDevice(device)) return false;

  const relay = resolveDeviceRelay(device, relayMap);
  const relayOperational =
    relay &&
    (relay.live_connected === true ||
      isRelayOperational(getRelayConnectionState(relay)));

  if (isRelayManagedDevice(device)) {
    return Boolean(relayOperational);
  }

  if (relayOperational) return true;

  if (!device.last_seen) return false;
  return now - new Date(device.last_seen).getTime() < LAST_SEEN_ONLINE_MS;
}

/** Operator-facing transport counts for fleet summary (matches list filter). */
export function computeDeviceTransportCounts(
  devices: DeviceOut[],
  relayMap: Record<string, RelayAgentOut>,
  now = Date.now()
): { online: number; offline: number; total: number } {
  let online = 0;
  for (const device of devices) {
    if (isDeviceOnlineForList(device, relayMap, now)) online += 1;
  }
  return { online, offline: devices.length - online, total: devices.length };
}
