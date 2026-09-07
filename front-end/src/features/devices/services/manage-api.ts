import { farmApi } from '@/lib/farm-api';
import { createSingleFlight } from '../lib/single-flight';

const DEVICE_POLL_TIMEOUT_MS = 10_000;

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
  adb_serial: string | null;
  relay_serial?: string | null;
  managed_by_org_id?: string | null;
  managed_by_relay_id?: string | null;
  adb_ip: string | null;
  adb_port: number;
  tags?: string;
  relay_id?: string | null;
  state: string;
};

export type DeviceListParams = {
  page: number;
  pageSize: number;
  q?: string;
  state?: string;
  sort?: 'last_seen_at' | '-last_seen_at';
};

export type AllocatedDeviceListParams = {
  q?: string;
  limit?: number;
};

export type DeviceListOut = {
  items: DeviceOut[];
  total: number;
  page: number;
  page_size: number;
  page_count: number;
};

export type DeviceStateCountsOut = {
  unknown: number;
  connecting: number;
  online: number;
  busy: number;
  reconnecting: number;
  dead: number;
  total: number;
};

export type SessionOwnerAnomalyOut = {
  session_id: string;
  device_id: string;
  device_serial: string;
  owner_type: string;
  owner_id: string | null;
  reason: string;
};

export type FleetStatsOut = {
  filters: {
    organization_id: string;
    group_id: string | null;
    relay_host: string | null;
  };
  devices: DeviceStateCountsOut;
  active_sessions: {
    user: number;
    execution: number;
    campaign: number;
    system: number;
    unknown: number;
    total: number;
  };
  owner_anomalies: SessionOwnerAnomalyOut[] | null;
};

export type ActiveFleetSessionListOut = {
  total: number;
  offset: number;
  limit: number;
  sessions: Array<{
    session_id: string;
    device_id: string;
    device_serial: string;
    device_name: string;
    owner_type: string;
    source: 'active_session' | 'busy_claim';
    created_at: string;
    duplicate_for_device: boolean;
  }>;
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
export type PairPollOut = {
  status: 'pending' | 'paired';
  device?: Record<string, unknown>;
};

const listDevices = createSingleFlight(() =>
  farmApi
    .get<DeviceOut[]>('/devices', { timeout: DEVICE_POLL_TIMEOUT_MS })
    .then((r) => r.data)
);

function clearDeviceListCache() {
  return undefined;
}

export const devicesApi = {
  list: listDevices,
  listPage: ({ page, pageSize, q, state, sort }: DeviceListParams) =>
    farmApi
      .get<DeviceListOut>('/devices', {
        params: {
          page,
          page_size: pageSize,
          q: q || undefined,
          state: state || undefined,
          sort
        },
        timeout: DEVICE_POLL_TIMEOUT_MS
      })
      .then((r) => r.data),
  create: (data: DeviceCreate) =>
    farmApi.post<DeviceOut>('/devices', data).then((r) => r.data),
  register: (body?: { name?: string; description?: string }) =>
    farmApi
      .post<DeviceOut>('/devices/register', body ?? {})
      .then((r) => r.data),
  listAllocated: ({ q, limit = 50 }: AllocatedDeviceListParams = {}) =>
    farmApi
      .get<DeviceOut[]>('/devices/allocated', {
        params: {
          q: q || undefined,
          limit
        },
        timeout: DEVICE_POLL_TIMEOUT_MS
      })
      .then((r) => r.data),
  claimAllocated: (deviceId: string) =>
    farmApi
      .post<DeviceOut>(`/devices/${encodeURIComponent(deviceId)}/claim`)
      .then((r) => {
        clearDeviceListCache();
        return r.data;
      }),
  connectManagedAgent: (deviceId: string, body?: { wsBaseUrl?: string }) =>
    farmApi
      .post<RelayCommandOut>(
        `/devices/${encodeURIComponent(deviceId)}/connect-via-managed-agent`,
        body ?? {}
      )
      .then((r) => r.data),
  sessions: (deviceId: string) =>
    farmApi
      .get<SessionOut[]>(`/devices/${deviceId}/sessions`)
      .then((r) => r.data),
  delete: (deviceId: string) =>
    farmApi.delete(`/devices/${deviceId}`).then((r) => r.data),
  pair: () =>
    farmApi
      .post<{ pairing_id: string; qr_url: string }>('/devices/pair')
      .then((r) => r.data),
  pairBulk: (count: number) =>
    farmApi
      .post<{ pairings: PairingOut[] }>('/devices/pair/bulk', { count })
      .then((r) => r.data),
  pollPair: (pairingId: string) =>
    farmApi.get<PairPollOut>(`/devices/pair/${pairingId}`).then((r) => {
      if (r.data.status === 'paired') {
        clearDeviceListCache();
      }
      return r.data;
    }),
  /** Backend chủ động kết nối tới thiết bị qua ADB TCP. Không cần QR. */
  connectByIp: (ip: string, port = 5555) =>
    farmApi
      .post<{
        ok: boolean;
        serial: string;
      }>('/devices/connect-adb', { ip, port })
      .then((r) => {
        clearDeviceListCache();
        return r.data;
      }),
  fleetStats: (params?: { group_id?: string; relay_host?: string }) => {
    const qs = new URLSearchParams();
    if (params?.group_id) qs.set('group_id', params.group_id);
    if (params?.relay_host) qs.set('relay_host', params.relay_host);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return farmApi
      .get<FleetStatsOut>(`/devices/fleet/stats${suffix}`)
      .then((r) => r.data);
  },
  activeSessions: (limit = 50, offset = 0) =>
    farmApi
      .get<ActiveFleetSessionListOut>('/devices/fleet/sessions', {
        params: { limit, offset }
      })
      .then((r) => r.data)
};

// ── Relay agent types ─────────────────────────────────────────────────────────

export type RelayAgentOut = {
  relay_id: string;
  name?: string;
  hostname: string;
  ip: string;
  version: string;
  serials: string[];
  device_names?: Record<string, string>;
  device_connections?: Record<string, RelayDeviceConnectionOut>;
  status: 'online' | 'offline';
  live_connected?: boolean;
  connected_at: string;
  last_heartbeat_at: string | null;
  disconnected_at: string | null;
};

export type RelayDeviceConnectionOut = {
  registered: boolean;
  device_id?: string | null;
  device_agent_connected: boolean;
};

export type RelayCommandOut = {
  ok: boolean;
  output: string;
  exit_code: number;
  error: string;
};

export type RelayDeviceRegisterResult = {
  serial: string;
  status: 'registered' | 'failed';
  device_id?: string | null;
  name?: string | null;
  message?: string | null;
};

export type BootstrapAllResult = {
  relay_id: string;
  total: number;
  ok: number;
  failed: number;
  results: Array<{
    serial: string;
    ok: boolean;
    output: string;
    error: string;
  }>;
};

export type RelayAgentTokenOut = {
  id: string;
  name: string;
  prefix: string;
  status: 'active' | 'revoked';
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

export type RelayAgentTokenCreated = RelayAgentTokenOut & {
  token: string;
};

export type RelayBatchJobItemOut = {
  id: string;
  serial: string;
  device_id: string | null;
  status: 'pending' | 'running' | 'ok' | 'failed' | 'skipped' | string;
  step: string;
  attempts: number;
  error: string;
  result: Record<string, unknown>;
};

export type RelayBatchJobOut = {
  id: string;
  relay_id: string;
  kind: 'provision' | 'claim_connect' | string;
  status:
    | 'pending'
    | 'running'
    | 'completed'
    | 'completed_with_errors'
    | 'failed'
    | 'cancelled'
    | string;
  total: number;
  ok: number;
  failed: number;
  pending: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
  items: RelayBatchJobItemOut[];
};

export type RelayBatchJobCreate = {
  serials?: string[];
  mode?: 'selected' | 'all_visible';
  connect?: boolean;
};

// ── Relay agents API ──────────────────────────────────────────────────────────

export const relayAgentsApi = {
  list: () => farmApi.get<RelayAgentOut[]>('/relay-agents').then((r) => r.data),
  get: (relayId: string) =>
    farmApi.get<RelayAgentOut>(`/relay-agents/${relayId}`).then((r) => r.data),
  registerDevice: (relayId: string, serial: string, body?: { name?: string }) =>
    farmApi
      .post<DeviceOut>(
        `/relay-agents/${encodeURIComponent(relayId)}/devices/${encodeURIComponent(serial)}/register`,
        body ?? {}
      )
      .then((r) => r.data),
  // Register several serials in one call. Empty/omitted `serials` = every
  // device the agent currently reports. Partial success: each device gets its
  // own result, so one failure does not sink the rest.
  registerDevices: (relayId: string, serials?: string[]) =>
    farmApi
      .post<{
        results: RelayDeviceRegisterResult[];
      }>(`/relay-agents/${encodeURIComponent(relayId)}/devices/register`, {
        serials: serials ?? []
      })
      .then((r) => r.data.results),
  pushConnectUrl: (
    relayId: string,
    serial: string,
    opts?: { deviceId?: string; wsBaseUrl?: string }
  ) =>
    farmApi
      .post<RelayCommandOut>(
        `/relay-agents/${encodeURIComponent(relayId)}/devices/${encodeURIComponent(serial)}/push-connect-url`,
        undefined,
        {
          params: {
            ...(opts?.deviceId ? { device_id: opts.deviceId } : {}),
            ...(opts?.wsBaseUrl ? { ws_base_url: opts.wsBaseUrl } : {})
          }
        }
      )
      .then((r) => r.data),
  connectDevice: (
    relayId: string,
    serial: string,
    opts?: { deviceId?: string; wsBaseUrl?: string }
  ) =>
    farmApi
      .post<RelayCommandOut>(
        `/relay-agents/${encodeURIComponent(relayId)}/devices/${encodeURIComponent(serial)}/connect`,
        undefined,
        {
          params: {
            ...(opts?.deviceId ? { device_id: opts.deviceId } : {}),
            ...(opts?.wsBaseUrl ? { ws_base_url: opts.wsBaseUrl } : {})
          }
        }
      )
      .then((r) => r.data),
  disconnectDevice: (
    relayId: string,
    serial: string,
    opts?: { deviceId?: string }
  ) =>
    farmApi
      .post<RelayCommandOut>(
        `/relay-agents/${encodeURIComponent(relayId)}/devices/${encodeURIComponent(serial)}/disconnect`,
        undefined,
        {
          params: {
            ...(opts?.deviceId ? { device_id: opts.deviceId } : {})
          }
        }
      )
      .then((r) => r.data),
  bootstrapAll: (relayId: string) =>
    farmApi
      .post<BootstrapAllResult>(`/relay-agents/${relayId}/bootstrap-all`)
      .then((r) => r.data),
  createProvisionJob: (relayId: string, body: RelayBatchJobCreate) =>
    farmApi
      .post<RelayBatchJobOut>(
        `/relay-agents/${encodeURIComponent(relayId)}/jobs/provision`,
        body
      )
      .then((r) => r.data),
  createClaimConnectJob: (relayId: string, body: RelayBatchJobCreate) =>
    farmApi
      .post<RelayBatchJobOut>(
        `/relay-agents/${encodeURIComponent(relayId)}/jobs/claim-connect`,
        body
      )
      .then((r) => r.data),
  getJob: (relayId: string, jobId: string) =>
    farmApi
      .get<RelayBatchJobOut>(
        `/relay-agents/${encodeURIComponent(relayId)}/jobs/${encodeURIComponent(jobId)}`
      )
      .then((r) => r.data),
  listJobItems: (
    relayId: string,
    jobId: string,
    params?: { status?: string; limit?: number; offset?: number }
  ) =>
    farmApi
      .get<
        RelayBatchJobItemOut[]
      >(`/relay-agents/${encodeURIComponent(relayId)}/jobs/${encodeURIComponent(jobId)}/items`, { params })
      .then((r) => r.data),
  listTokens: () =>
    farmApi
      .get<RelayAgentTokenOut[]>('/relay-agents/tokens')
      .then((r) => r.data),
  createToken: (body: { name?: string }) =>
    farmApi
      .post<RelayAgentTokenCreated>('/relay-agents/tokens', body)
      .then((r) => r.data),
  revokeToken: (tokenId: string) =>
    farmApi
      .delete(`/relay-agents/tokens/${encodeURIComponent(tokenId)}`)
      .then((r) => r.data)
};

// ── Device relay control API ──────────────────────────────────────────────────

export type DeviceReviveOut = {
  device_id: string;
  from_state: string;
  to_state: string;
  actor: string;
};

export const deviceControlApi = {
  bootstrap: (deviceId: string) =>
    farmApi
      .post<RelayCommandOut>(`/devices/${deviceId}/bootstrap`)
      .then((r) => r.data),
  restartU2: (deviceId: string) =>
    farmApi
      .post<RelayCommandOut>(`/devices/${deviceId}/restart-u2`)
      .then((r) => r.data),
  restartAtx: (deviceId: string) =>
    farmApi
      .post<RelayCommandOut>(`/devices/${deviceId}/restart-atx`)
      .then((r) => r.data),
  restartScrcpy: (deviceId: string) =>
    farmApi
      .post<RelayCommandOut>(`/devices/${deviceId}/restart-scrcpy`)
      .then((r) => r.data),
  /** Admin: DEAD → CONNECTING (DF-T-02-005). */
  revive: (deviceId: string) =>
    farmApi
      .post<DeviceReviveOut>(`/devices/${deviceId}/revive`)
      .then((r) => r.data)
};
