import {
  deviceDisplayName,
  type DeviceDisplayLike
} from './device-display-name';

/** Bounded label for device Select (long model/serial otherwise breaks the top bar). */
export function formatDeviceSelectLabel(
  d: DeviceDisplayLike & { serial: string }
) {
  const left = deviceSelectDisplayName(d);
  const s = d.serial;
  const serialShort = s.length > 16 ? `${s.slice(0, 7)}…${s.slice(-6)}` : s;
  if (!left) return serialShort;
  const maxLeft = 26;
  const leftShort =
    left.length > maxLeft ? `${left.slice(0, maxLeft - 1)}…` : left;
  return `${leftShort} — ${serialShort}`;
}

export function deviceSelectDisplayName(d: DeviceDisplayLike): string {
  return deviceDisplayName(d, '').replace(/\s+/g, ' ');
}

export function deviceSelectFullTitle(
  d: DeviceDisplayLike & { serial: string }
) {
  const left = deviceSelectDisplayName(d);
  return left ? `${left} — ${d.serial}` : d.serial;
}
