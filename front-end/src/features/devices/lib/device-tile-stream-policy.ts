export type DeviceScreenState = 'live' | 'paused' | 'inactive';

export function resolveDeviceScreenState(
  deviceActive: boolean,
  streamEnabled: boolean | undefined
): DeviceScreenState {
  if (!deviceActive) return 'inactive';
  return streamEnabled === false ? 'paused' : 'live';
}

export function shouldMountDeviceScreen(
  deviceActive: boolean,
  streamEnabled: boolean | undefined
): boolean {
  return resolveDeviceScreenState(deviceActive, streamEnabled) === 'live';
}
