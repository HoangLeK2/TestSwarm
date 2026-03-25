export interface Device {
  serial: string;
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
    }
  | { type: 'log'; serial: string; line: string }
  | { type: 'ws_status'; connected: boolean };

