export interface Device {
  serial: string;
  registered_serial?: string;
  name?: string;
  display_name?: string;
  brand: string;
  model: string;
  state: string;
  battery: number;
  current_app?: string;
  screen_width?: number;
  screen_height?: number;
  /** How touch is delivered: a11y | minitouch | u2 (uiautomator2) | none */
  touch_method?: string;
  minitouch_ready?: boolean;
  u2_ready?: boolean;
  agent_connected?: boolean;
  stf_connected?: boolean;
  /** Media-plane liveness from local media-adapter, independent from agent-boot control. */
  media_adapter_connected?: boolean;
  media_stream_active?: boolean;
  media_stream_connected?: boolean;
  media_stream_name?: string;
  media_stream_source?: string;
  media_stream_last_frame_unix_ms?: number;
  /** Server-clock stamp of when the adapter's frame counter last moved. */
  media_stream_frame_progress_unix_ms?: number;
  relay_scrcpy_enabled?: boolean;
  /** >0 when a Temporal scenario/campaign is actively driving this device */
  scenario_active?: number;
  /** Current server-side session ownership, for example idle or reserved. */
  usage_state?: string;
  /** True after operator paused automation to take manual control. */
  manual_takeover_active?: boolean;
  /** Campaign/scenario currently executing on this device, null when idle. */
  active_run?: DeviceActiveRun | null;
  health?: DeviceHealth;
}

export interface DeviceActiveRun {
  execution_id: string;
  campaign_id?: string | null;
  campaign_name?: string | null;
  scenario_id?: string | null;
  scenario_name?: string | null;
}

export type DeviceHealthStatus =
  | 'ready'
  | 'degraded'
  | 'busy'
  | 'offline'
  | 'unknown';

export interface DeviceHealth {
  overall: DeviceHealthStatus;
  agent: {
    status: 'online' | 'offline' | 'unknown';
    observed_at?: string | null;
    reason?: string | null;
  };
  stream: {
    /** 'stale' = channel still claims to be up but no new frames are arriving. */
    status: 'ready' | 'starting' | 'stale' | 'unavailable' | 'error';
    observed_at?: string | null;
    reason?: string | null;
  };
  command: {
    status: 'ready' | 'busy' | 'unavailable';
    reason?: string | null;
  };
  heartbeat_at?: string | null;
  last_signal_at?: string | null;
  last_signal_source?: 'live_transport' | 'heartbeat';
  evaluated_at: string;
  reason_codes: string[];
}

export interface Task {
  id: string;
  name: string;
  status: string;
  target?: string;
  retry_count: number;
  max_retries: number;
  error?: string;
}

export type WsMessage =
  | {
      type: 'frame';
      serial: string;
      jpeg_b64?: string;
      codec?: 'h264';
      key?: boolean;
      data?: string;
      codec_string?: string;
      device_width?: number;
      device_height?: number;
      frame_width?: number;
      frame_height?: number;
      scale_x?: number;
      scale_y?: number;
    }
  | {
      type: 'status';
      serial: string;
      brand?: string;
      model?: string;
      state?: string;
      battery?: number;
      current_app?: string;
      screen_width?: number;
      screen_height?: number;
      device_width?: number;
      device_height?: number;
      touch_method?: string;
      minitouch_ready?: boolean;
      u2_ready?: boolean;
      agent_connected?: boolean;
      stf_connected?: boolean;
      scenario_active?: number;
      manual_takeover_active?: boolean;
    }
  | { type: 'log'; serial: string; line: string }
  | { type: 'ws_status'; connected: boolean }
  | {
      type: 'device_busy';
      serial: string;
      reason: string;
      scenario_active: boolean;
    }
  | {
      type: 'multi_action_result';
      request_id: string;
      ok: boolean;
      count: number;
      error?: string;
      results: Array<{
        serial: string;
        ok: boolean;
        error?: string;
        message?: string;
        latency_ms?: number;
      }>;
    }
  | {
      type: 'notification';
      data: import('@/features/notifications/services/api').NotificationItem;
    }
  | {
      type: 'device_event';
      id: string;
      serial: string;
      event: string;
      reason?: string;
      old_state?: string;
      new_state?: string;
      device_model?: string;
      device_brand?: string;
      extra_data?: Record<string, unknown>;
      created_at: string;
    };

export interface DeviceEvent {
  id: string;
  serial: string;
  event: string;
  reason?: string;
  old_state?: string;
  new_state?: string;
  device_model?: string;
  device_brand?: string;
  extra_data?: Record<string, unknown>;
  created_at: string;
}

/** Subset of GET /api/config used by Device Farm grid tiles. */
export type DeviceFarmStreamingConfig = {
  mode: string;
  autoAttachScrcpy: boolean;
  autoAttachScrcpyOnRelayOnline: boolean;
  webrtcEnabled?: boolean;
};
