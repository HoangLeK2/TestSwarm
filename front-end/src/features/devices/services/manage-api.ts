import { farmApi } from '@/lib/farm-api';

export type DeviceOut = {
  id: string;
  serial: string;
  name: string;
  device_key: string;
  user_id: string | null;
  brand: string;
  model: string;
  android_version: string;
  sdk_version: number;
  screen_width: number;
  screen_height: number;
  last_seen: string | null;
  created_at: string;
  adb_ip: string | null;
  adb_port: number;
  tags?: string;
};

export type DeviceCreate = { serial: string; name?: string };

export type SessionOut = {
  id: string;
  client_ip: string;
  connected_at: string;
  disconnected_at: string | null;
};

export const PENDING_SERIAL_PREFIX = 'pending-';

export function isPendingDevice(device: { serial: string }): boolean {
  return device.serial.startsWith(PENDING_SERIAL_PREFIX);
}

export type PairingOut = { pairing_id: string; qr_url: string };
export type PairPollOut = { status: 'pending' | 'paired'; device?: Record<string, unknown> };

export const devicesApi = {
  list: () => farmApi.get<DeviceOut[]>('/devices').then((r) => r.data),
  create: (data: DeviceCreate) => farmApi.post<DeviceOut>('/devices', data).then((r) => r.data),
  register: (body?: { name?: string; description?: string }) =>
    farmApi.post<DeviceOut>('/devices/register', body ?? {}).then((r) => r.data),
  sessions: (deviceId: string) =>
    farmApi.get<SessionOut[]>(`/devices/${deviceId}/sessions`).then((r) => r.data),
  delete: (deviceId: string) => farmApi.delete(`/devices/${deviceId}`).then((r) => r.data),
  pair: () => farmApi.post<{ pairing_id: string; qr_url: string }>('/devices/pair').then((r) => r.data),
  pairBulk: (count: number) =>
    farmApi.post<{ pairings: PairingOut[] }>('/devices/pair/bulk', { count }).then((r) => r.data),
  pollPair: (pairingId: string) =>
    farmApi.get<PairPollOut>(`/devices/pair/${pairingId}`).then((r) => r.data),
  /** Backend chủ động kết nối tới thiết bị qua ADB TCP. Không cần QR. */
  connectByIp: (ip: string, port = 5555) =>
    farmApi.post<{ ok: boolean; serial: string }>('/devices/connect-adb', { ip, port }).then((r) => r.data)
};
