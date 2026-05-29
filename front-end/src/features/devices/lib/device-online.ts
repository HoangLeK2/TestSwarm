import {
  isPendingDevice,
  type DeviceOut,
  type RelayAgentOut
} from '../services/manage-api';

const LAST_SEEN_ONLINE_MS = 60_000;

/** Resolve the relay agent currently associated with a registered device. */
export function resolveDeviceRelay(
  device: DeviceOut,
  relayMap: Record<string, RelayAgentOut>
): RelayAgentOut | undefined {
  return (
    (device.relay_id ? relayMap[device.relay_id] : undefined) ??
    relayMap[device.serial] ??
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
  if (relay?.status === 'online') return true;

  if (!device.last_seen) return false;
  return now - new Date(device.last_seen).getTime() < LAST_SEEN_ONLINE_MS;
}
