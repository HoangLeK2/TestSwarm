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

/** Fetch full screenshot as base64 for visual anchoring. */
export async function fetchScreenshotB64(
  serial: string,
): Promise<{ screenshot: string; width: number; height: number }> {
  const { data } = await farmApi.get(`/screenshot-b64/${encodeURIComponent(serial)}`);
  return data as { screenshot: string; width: number; height: number };
}

/**
 * Crop a base64 JPEG image client-side using Canvas API.
 * ratioCrop values are in 0–1 relative to image dimensions.
 * Returns base64 JPEG of the cropped region, or undefined if crop is invalid.
 */
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
      if (cw <= 0 || ch <= 0) { resolve(undefined); return; }
      const canvas = document.createElement('canvas');
      canvas.width = cw;
      canvas.height = ch;
      const ctx = canvas.getContext('2d');
      if (!ctx) { resolve(undefined); return; }
      ctx.drawImage(img, x1, y1, cw, ch, 0, 0, cw, ch);
      // Strip "data:image/jpeg;base64," prefix
      const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
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

/**
 * Stream scenario preview via SSE — emits step results in real-time as each step completes.
 * Events: { event: 'start', total_steps }, { event: 'step_done', index, ok, ... }, { event: 'done', ... }
 */
export async function previewScenarioStream(
  serial: string,
  steps: Array<Record<string, any>>,
  onEvent: (event: { event: string; [key: string]: any }) => void,
  signal?: AbortSignal,
): Promise<void> {
  // Use farmApi's baseURL for the SSE endpoint
  const baseUrl = farmApi.defaults.baseURL || '';
  const url = `${baseUrl}/devices/${encodeURIComponent(serial)}/scenario/preview-stream`;

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ steps }),
    signal,
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
        } catch { /* skip malformed */ }
      }
    }
  }
}

