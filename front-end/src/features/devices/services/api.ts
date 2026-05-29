import { farmApi } from '@/lib/farm-api';
import { tokenStorage } from '@/lib/token-storage';
import type { Device, DeviceEvent, Task } from '../types';

export type PreviewStepResult = {
  index: number;
  type?: string;
  ok: boolean;
  message?: string;
};

export type PreviewScenarioResponse = {
  serial: string;
  steps_executed: number;
  step_results?: PreviewStepResult[];
};

export interface AppConfig {
  wifi_densepose_url?: string;
}

const hierarchyInFlight = new Map<string, Promise<string>>();
const hierarchyFailureUntil = new Map<string, number>();
const HIERARCHY_503_COOLDOWN_MS = 2500;

export async function fetchDevices(): Promise<Device[]> {
  const { data } = await farmApi.get<Device[]>('/devices');
  return data;
}

export type LiveDevicesResponse = {
  total: number;
  offset: number;
  limit: number | null;
  devices: Device[];
};

/** Live device list from WebSocket agent registry (no-ADB dashboard). Use this for device farm grid. */
export async function fetchLiveDevices(opts?: {
  state?: string;
  model?: string;
  limit?: number;
  offset?: number;
}): Promise<Device[]> {
  const params = new URLSearchParams();
  if (opts?.state) params.set('state', opts.state);
  if (opts?.model) params.set('model', opts.model);
  if (opts?.limit != null) params.set('limit', String(opts.limit));
  if (opts?.offset) params.set('offset', String(opts.offset));
  const qs = params.toString() ? `?${params.toString()}` : '';
  const { data } = await farmApi.get<LiveDevicesResponse | Device[]>(
    `/devices/live${qs}`
  );
  if (Array.isArray(data)) return data;
  if (data && Array.isArray((data as LiveDevicesResponse).devices))
    return (data as LiveDevicesResponse).devices;
  return [];
}

export type FleetRunResult = {
  run_id: string;
  dispatched: number;
  task_ids: string[];
  device_serials: string[];
};

export type FleetStatusResult = {
  run_id: string | null;
  total: number;
  pending: number;
  running: number;
  done: number;
  failed: number;
  cancelled: number;
  progress_pct: number;
  all_complete: boolean;
};

export async function fleetRun(
  steps: Array<Record<string, unknown>>,
  opts?: { filter_state?: string; filter_model?: string; max_devices?: number }
): Promise<FleetRunResult> {
  const { data } = await farmApi.post<FleetRunResult>('/fleet/run', {
    steps,
    filter_state: opts?.filter_state ?? 'READY',
    ...(opts?.filter_model ? { filter_model: opts.filter_model } : {}),
    ...(opts?.max_devices != null ? { max_devices: opts.max_devices } : {})
  });
  return data;
}

export async function fleetStatus(runId?: string): Promise<FleetStatusResult> {
  const url = runId
    ? `/fleet/status?run_id=${encodeURIComponent(runId)}`
    : '/fleet/status';
  const { data } = await farmApi.get<FleetStatusResult>(url);
  return data;
}

export async function fetchTasks(): Promise<Task[]> {
  const { data } = await farmApi.get<Task[]>('/tasks');
  return Array.isArray(data) ? data : [];
}

export async function restartDevice(serial: string): Promise<unknown> {
  const { data } = await farmApi.post(
    `/device/${encodeURIComponent(serial)}/restart`
  );
  return data;
}

/** UI hierarchy XML (uiautomator2 page source). refresh=true skips backend cache (force fresh dump). On 503 returns "". */
export async function fetchHierarchy(
  serial: string,
  refresh = false
): Promise<string> {
  const key = serial;
  const now = Date.now();
  if ((hierarchyFailureUntil.get(key) ?? 0) > now) return '';
  const pending = hierarchyInFlight.get(key);
  if (pending) return pending;

  // Respect safe-mode: if the backend has stream_hierarchy=false, skip the
  // request entirely so we don't spam the network with 503s.
  const task = (async () => {
    try {
      const { isHierarchyEnabled } = await import(
        '@/features/core/services/safe-mode'
      );
      if (!isHierarchyEnabled()) return '';
    } catch {
      /* module not available — fall through */
    }
    const url = refresh
      ? `/devices/${encodeURIComponent(serial)}/hierarchy?refresh=1`
      : `/devices/${encodeURIComponent(serial)}/hierarchy`;
    try {
      const { data } = await farmApi.get<string>(url, { responseType: 'text' });
      hierarchyFailureUntil.delete(key);
      return typeof data === 'string' ? data : '';
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response
        ?.status;
      if (status === 503) {
        hierarchyFailureUntil.set(key, Date.now() + HIERARCHY_503_COOLDOWN_MS);
        return '';
      }
      throw err;
    } finally {
      hierarchyInFlight.delete(key);
    }
  })();
  hierarchyInFlight.set(key, task);
  return task;
}

/** Fetch full screenshot as base64 for visual anchoring. */
export async function fetchScreenshotB64(
  serial: string
): Promise<{ screenshot: string; width: number; height: number }> {
  const { data } = await farmApi.get(
    `/screenshot-b64/${encodeURIComponent(serial)}`
  );
  return data as { screenshot: string; width: number; height: number };
}

/**
 * Crop a base64 JPEG image client-side using Canvas API.
 * ratioCrop values are in 0–1 relative to image dimensions.
 * Returns base64 JPEG of the cropped region, or undefined if crop is invalid.
 */
/** Minimum crop dimension in pixels — smaller crops are too small for template matching. */
const MIN_CROP_PX = 20;

export async function cropBase64(
  b64: string,
  ratioCrop: { rx1: number; ry1: number; rx2: number; ry2: number }
): Promise<string | undefined> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const iw = img.naturalWidth;
      const ih = img.naturalHeight;
      const x1 = Math.round(ratioCrop.rx1 * iw);
      const y1 = Math.round(ratioCrop.ry1 * ih);
      const x2 = Math.round(ratioCrop.rx2 * iw);
      const y2 = Math.round(ratioCrop.ry2 * ih);
      const cw = x2 - x1;
      const ch = y2 - y1;
      // Reject crops that are too small to be useful for template matching
      if (cw < MIN_CROP_PX || ch < MIN_CROP_PX) {
        resolve(undefined);
        return;
      }
      const canvas = document.createElement('canvas');
      canvas.width = cw;
      canvas.height = ch;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        resolve(undefined);
        return;
      }
      ctx.drawImage(img, x1, y1, cw, ch, 0, 0, cw, ch);
      // Strip "data:image/jpeg;base64," prefix. Quality 0.80 is sufficient
      // for image template matching and keeps file size reasonable.
      const dataUrl = canvas.toDataURL('image/jpeg', 0.8);
      resolve(dataUrl.split(',')[1]);
    };
    img.onerror = () => resolve(undefined);
    img.src = `data:image/jpeg;base64,${b64}`;
  });
}

/** Tap by selector (resource-id, text, xpath). Uses uiautomator2. */
export async function tapSelector(
  serial: string,
  by: 'resource-id' | 'text' | 'xpath' | 'class name',
  value: string
): Promise<void> {
  await farmApi.post(`/tap_selector/${encodeURIComponent(serial)}`, {
    by,
    value
  });
}

/** Given tap coordinates (pixels), infer a friendly selector from current UI hierarchy. */
export async function hitTestSelector(
  serial: string,
  rx: number,
  ry: number
): Promise<{
  by: 'resource-id' | 'text' | 'xpath' | 'class name';
  value: string;
} | null> {
  const { data } = await farmApi.post<{
    by: string | null;
    value: string | null;
  }>(`/devices/${encodeURIComponent(serial)}/hit_test`, { rx, ry });
  if (!data || !data.by || !data.value) return null;
  return {
    by: data.by as 'resource-id' | 'text' | 'xpath' | 'class name',
    value: data.value
  };
}

export type FetchEventsResponse = {
  total: number;
  offset: number;
  limit: number;
  events: DeviceEvent[];
};

/** Fetch device events from DB (persistent history). */
export async function fetchEvents(opts?: {
  serial?: string;
  event?: string;
  limit?: number;
  offset?: number;
}): Promise<FetchEventsResponse> {
  const params = new URLSearchParams();
  if (opts?.serial) params.set('serial', opts.serial);
  if (opts?.event) params.set('event', opts.event);
  if (opts?.limit != null) params.set('limit', String(opts.limit));
  if (opts?.offset != null) params.set('offset', String(opts.offset));
  const qs = params.toString() ? `?${params.toString()}` : '';
  const { data } = await farmApi.get<FetchEventsResponse>(`/events${qs}`);
  return data;
}

export async function fetchConfig(): Promise<AppConfig> {
  const { data } = await farmApi.get<AppConfig>('/config');
  return data;
}

export interface StfBattery {
  level: number;
  status: number;
  health: number;
  source: number;
  temp: number;
  voltage: number;
}

export interface StfConnectivity {
  connected: boolean;
  type: number;
  subtype: number;
  roaming: boolean;
}

export interface StfPhoneState {
  state: number;
  operator: string;
}

export interface StfStatus {
  connected: boolean;
  battery: StfBattery;
  rotation: number;
  connectivity: StfConnectivity;
  airplane_mode: boolean;
  phone_state: StfPhoneState;
}

export async function stfStatus(serial: string): Promise<StfStatus | null> {
  try {
    const { data } = await farmApi.get<StfStatus>(
      `/stf/status/${encodeURIComponent(serial)}`
    );
    return data;
  } catch {
    return null;
  }
}

export async function stfGetClipboard(serial: string): Promise<string | null> {
  try {
    const { data } = await farmApi.get<{ text: string }>(
      `/stf/clipboard/${encodeURIComponent(serial)}`
    );
    return data.text;
  } catch {
    return null;
  }
}

export async function stfSetClipboard(
  serial: string,
  text: string
): Promise<boolean> {
  try {
    const { data } = await farmApi.post<{ ok: boolean }>(
      `/stf/clipboard/${encodeURIComponent(serial)}`,
      { text }
    );
    return data.ok;
  } catch {
    return false;
  }
}

export async function stfSetWifi(
  serial: string,
  enabled: boolean
): Promise<boolean> {
  try {
    const { data } = await farmApi.post<{ ok: boolean }>(
      `/stf/wifi/${encodeURIComponent(serial)}`,
      { enabled }
    );
    return data.ok;
  } catch {
    return false;
  }
}

export async function stfSetBluetooth(
  serial: string,
  enabled: boolean
): Promise<boolean> {
  try {
    const { data } = await farmApi.post<{ ok: boolean }>(
      `/stf/bluetooth/${encodeURIComponent(serial)}`,
      { enabled }
    );
    return data.ok;
  } catch {
    return false;
  }
}

export async function stfSetKeyguard(
  serial: string,
  enabled: boolean
): Promise<boolean> {
  try {
    const { data } = await farmApi.post<{ ok: boolean }>(
      `/stf/keyguard/${encodeURIComponent(serial)}`,
      { enabled }
    );
    return data.ok;
  } catch {
    return false;
  }
}

export async function stfSetWakeLock(
  serial: string,
  enabled: boolean
): Promise<boolean> {
  try {
    const { data } = await farmApi.post<{ ok: boolean }>(
      `/stf/wakelock/${encodeURIComponent(serial)}`,
      { enabled }
    );
    return data.ok;
  } catch {
    return false;
  }
}

export async function stfSetRinger(
  serial: string,
  mode: 'silent' | 'vibrate' | 'normal'
): Promise<boolean> {
  try {
    const { data } = await farmApi.post<{ ok: boolean }>(
      `/stf/ringer/${encodeURIComponent(serial)}`,
      { mode }
    );
    return data.ok;
  } catch {
    return false;
  }
}

export async function stfSetMute(
  serial: string,
  enabled: boolean
): Promise<boolean> {
  try {
    const { data } = await farmApi.post<{ ok: boolean }>(
      `/stf/mute/${encodeURIComponent(serial)}`,
      { enabled }
    );
    return data.ok;
  } catch {
    return false;
  }
}

export async function stfIdentify(serial: string): Promise<boolean> {
  try {
    const { data } = await farmApi.post<{ ok: boolean }>(
      `/stf/identify/${encodeURIComponent(serial)}`
    );
    return data.ok;
  } catch {
    return false;
  }
}

export async function stfGetDisplay(
  serial: string
): Promise<Record<string, unknown> | null> {
  try {
    const { data } = await farmApi.get(
      `/stf/display/${encodeURIComponent(serial)}`
    );
    return data as Record<string, unknown>;
  } catch {
    return null;
  }
}

export async function stfGetProperties(
  serial: string
): Promise<Record<string, unknown> | null> {
  try {
    const { data } = await farmApi.get(
      `/stf/properties/${encodeURIComponent(serial)}`
    );
    return data as Record<string, unknown>;
  } catch {
    return null;
  }
}

export async function previewScenario(
  serial: string,
  steps: Array<Record<string, any>>
): Promise<PreviewScenarioResponse> {
  const { data } = await farmApi.post<PreviewScenarioResponse>(
    `/devices/${encodeURIComponent(serial)}/scenario/preview`,
    { steps }
  );
  return data;
}

/**
 * Stream scenario preview via SSE — emits step results in real-time as each step completes.
 * Events: { event: 'start', total_steps }, { event: 'step_done', index, ok, ... }, { event: 'done', ... }
 */
export async function previewScenarioStream(
  serial: string,
  steps: Array<Record<string, any>>,
  onEvent: (event: { event: string; [key: string]: any }) => void,
  signal?: AbortSignal,
  variables?: Record<string, any>,
  accountGroupId?: string | null,
  scenarioId?: string | null,
  scenarioDeviceVars?: Record<string, any> | null
): Promise<void> {
  // Use farmApi's baseURL for the SSE endpoint
  const baseUrl = farmApi.defaults.baseURL || '';
  const url = `${baseUrl}/devices/${encodeURIComponent(serial)}/scenario/preview-stream`;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json'
  };
  const rawToken = tokenStorage.getAuthToken();
  if (rawToken) headers['Authorization'] = `Bearer ${rawToken}`;

  const body: Record<string, any> = { steps, variables: variables ?? {} };
  if (accountGroupId) body.account_group_id = accountGroupId;
  if (scenarioId) body.scenario_id = scenarioId;
  if (scenarioDeviceVars && Object.keys(scenarioDeviceVars).length > 0) {
    body.scenario_device_vars = scenarioDeviceVars;
  }

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal
  });

  if (!response.ok || !response.body) {
    throw new Error(`SSE error: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Parse SSE lines
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6));
          onEvent(data);
        } catch {
          /* skip malformed */
        }
      }
    }
  }
}

/** Explicit cancel for a preview-stream by (serial, trace_id). Idempotent:
 * 404 after natural finish is expected and swallowed. Use this from unmount
 * cleanup so the server drops the scenario even if the SSE TCP close has not
 * yet been observed by `request.is_disconnected()` on the server side.
 */
export async function cancelPreviewStream(
  serial: string,
  traceId: string
): Promise<void> {
  try {
    await farmApi.post(
      `/devices/${encodeURIComponent(serial)}/scenario/preview-stream/${encodeURIComponent(traceId)}/cancel`
    );
  } catch {
    /* stream already finished / trace unknown — ignore */
  }
}

/** Cancel all running scenarios on a device so the user can take manual control. */
export async function interruptDevice(
  serial: string
): Promise<{ ok: boolean; cancelled_workflows: string[] }> {
  const { data } = await farmApi.post<{
    ok: boolean;
    cancelled_workflows: string[];
  }>(`/devices/${encodeURIComponent(serial)}/interrupt`);
  return data;
}
