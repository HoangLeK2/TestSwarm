import type { Device } from '../types';
import type { DeviceOut } from '../services/manage-api';

export function filterVisibleDeviceFarmDevices(
  devices: Device[],
  registeredDevices: DeviceOut[]
): Device[] {
  const registeredSerials = new Set(registeredDevices.map((d) => d.serial));

  return devices.filter((device) => {
    const registeredSerial = device.registered_serial ?? device.serial;
    if (!registeredSerials.has(registeredSerial)) return false;
    return true;
  });
}
