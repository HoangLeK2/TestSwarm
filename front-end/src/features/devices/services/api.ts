import { farmApi } from '@/lib/farm-api';
import type { Device, Task } from '../types';

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
  const { data } = await farmApi.get<LiveDevicesResponse | Device[]>(`/devices/live${qs}`);
  if (Array.isArray(data)) return data;
  if (data && Array.isArray((data as LiveDevicesResponse).devices)) return (data as LiveDevicesResponse).devices;
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
    ...(opts?.max_devices != null ? { max_devices: opts.max_devices } : {}),
  });
  return data;
}

export async function fleetStatus(runId?: string): Promise<FleetStatusResult> {
  const url = runId ? `/fleet/status?run_id=${encodeURIComponent(runId)}` : '/fleet/status';
  const { data } = await farmApi.get<FleetStatusResult>(url);
  return data;
}

export async function fetchTasks(): Promise<Task[]> {
  const { data } = await farmApi.get<Task[]>('/tasks');
  return Array.isArray(data) ? data : [];
}

export async function restartDevice(serial: string): Promise<unknown> {
  const { data } = await farmApi.post(`/device/${encodeURIComponent(serial)}/restart`);
  return data;
}

/** UI hierarchy XML (uiautomator2 page source). refresh=true skips backend cache (force fresh dump). On 503 returns "". */
export async function fetchHierarchy(serial: string, refresh = false): Promise<string> {
  const url = refresh
    ? `/devices/${encodeURIComponent(serial)}/hierarchy?refresh=1`
    : `/devices/${encodeURIComponent(serial)}/hierarchy`;
  try {
    const { data } = await farmApi.get<string>(url, { responseType: 'text' });
    return typeof data === 'string' ? data : '';
  } catch (err: unknown) {
    const status = (err as { response?: { status?: number } })?.response?.status;
    if (status === 503) return '';
    throw err;
  }
}

/** Tap by selector (resource-id, text, xpath). Uses uiautomator2. */
export async function tapSelector(
  serial: string,
  by: 'resource-id' | 'text' | 'xpath' | 'class name',
  value: string
): Promise<void> {
  await farmApi.post(`/tap_selector/${encodeURIComponent(serial)}`, { by, value });
}

/** Given tap coordinates (pixels), infer a friendly selector from current UI hierarchy. */
export async function hitTestSelector(
  serial: string,
  rx: number,
  ry: number
): Promise<{ by: 'resource-id' | 'text' | 'xpath' | 'class name'; value: string } | null> {
  const { data } = await farmApi.post<{ by: string | null; value: string | null }>(
    `/devices/${encodeURIComponent(serial)}/hit_test`,
    { rx, ry }
  );
  if (!data || !data.by || !data.value) return null;
  return { by: data.by as 'resource-id' | 'text' | 'xpath' | 'class name', value: data.value };
}

export async function fetchConfig(): Promise<AppConfig> {
  const { data } = await farmApi.get<AppConfig>('/config');
  return data;
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

