import type { Device, WsMessage } from '../types';

type StatusMessage = Extract<WsMessage, { type: 'status' }>;

const OFFLINE_STATES = new Set(['DISCONNECTED', 'DEAD']);

function normalizeState(state: string | null | undefined): string {
  return String(state || '')
    .replace('DeviceState.', '')
    .trim()
    .toUpperCase();
}

function isOfflineStatus(message: StatusMessage): boolean {
  return OFFLINE_STATES.has(normalizeState(message.state));
}

function deviceFromStatus(message: StatusMessage): Device {
  const screenWidth = message.device_width ?? message.screen_width;
  const screenHeight = message.device_height ?? message.screen_height;

  return {
    serial: message.serial,
    brand: message.brand ?? '',
    model: message.model ?? '',
    state: message.state ?? 'CONNECTING',
    battery: message.battery ?? -1,
    current_app: message.current_app ?? '',
    screen_width: screenWidth,
    screen_height: screenHeight,
    touch_method: message.touch_method,
    minitouch_ready: message.minitouch_ready,
    u2_ready: message.u2_ready,
    agent_connected: message.agent_connected,
    stf_connected: message.stf_connected,
    scenario_active: message.scenario_active ?? 0,
    manual_takeover_active: Boolean(message.manual_takeover_active)
  };
}

function mergeStatusIntoDevice(device: Device, message: StatusMessage): Device {
  return {
    ...device,
    state: message.state ?? device.state,
    battery: message.battery ?? device.battery,
    current_app: message.current_app ?? device.current_app,
    screen_width:
      message.device_width ?? message.screen_width ?? device.screen_width,
    screen_height:
      message.device_height ?? message.screen_height ?? device.screen_height,
    touch_method: message.touch_method ?? device.touch_method,
    minitouch_ready: message.minitouch_ready ?? device.minitouch_ready,
    u2_ready: message.u2_ready ?? device.u2_ready,
    agent_connected: message.agent_connected ?? device.agent_connected,
    stf_connected: message.stf_connected ?? device.stf_connected,
    scenario_active:
      'scenario_active' in message
        ? (message.scenario_active ?? 0)
        : device.scenario_active,
    manual_takeover_active:
      'manual_takeover_active' in message
        ? Boolean(message.manual_takeover_active)
        : device.manual_takeover_active
  };
}

export function mergeDeviceFarmWsStatus(
  previous: Device[],
  message: StatusMessage,
  options: { liveSnapshotAuthoritative?: boolean } = {}
): Device[] {
  if (options.liveSnapshotAuthoritative && isOfflineStatus(message)) {
    return previous;
  }

  const exists = previous.some((device) => device.serial === message.serial);
  if (!exists) return [...previous, deviceFromStatus(message)];

  return previous.map((device) =>
    device.serial === message.serial
      ? mergeStatusIntoDevice(device, message)
      : device
  );
}
