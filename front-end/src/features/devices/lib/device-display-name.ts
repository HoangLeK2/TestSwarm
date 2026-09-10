export type DeviceDisplayLike = {
  serial?: string | null;
  registered_serial?: string | null;
  name?: string | null;
  display_name?: string | null;
  brand?: string | null;
  model?: string | null;
};

function clean(value: string | null | undefined): string {
  return String(value ?? '').trim();
}

export function deviceModelLabel(device: DeviceDisplayLike): string {
  return [clean(device.brand), clean(device.model)].filter(Boolean).join(' ');
}

export function deviceDisplayName(
  device: DeviceDisplayLike,
  fallback = '—'
): string {
  return (
    clean(device.name) ||
    clean(device.display_name) ||
    deviceModelLabel(device) ||
    clean(device.registered_serial) ||
    clean(device.serial) ||
    fallback
  );
}

export function devicePrimarySerial(device: DeviceDisplayLike): string {
  return clean(device.registered_serial) || clean(device.serial);
}

export function shortDeviceSerial(
  serial: string | null | undefined,
  visibleTail = 8
): string {
  const value = clean(serial);
  if (!value) return '';
  if (value.length <= visibleTail + 4) return value;
  return `…${value.slice(-visibleTail)}`;
}

export function deviceSecondarySerial(device: DeviceDisplayLike): string {
  const serial = devicePrimarySerial(device);
  const label = deviceDisplayName(device, '');
  return serial && serial !== label ? serial : '';
}
