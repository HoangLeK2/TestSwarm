import type { WsMessage } from '../types';
import { tokenStorage } from '@/lib/token-storage';
import { FrameDispatcher, parseBinaryFrame } from './frame-dispatcher';

function normalizeWsUrl(raw: string, fallbackScheme: 'ws' | 'wss') {
  const trimmed = raw.trim().replace(/^['"]|['"]$/g, '');
  if (!trimmed) return null;

  let candidate = trimmed;
  if (candidate.startsWith('ws://') || candidate.startsWith('wss://')) {
    // ok
  } else if (candidate.startsWith('http://')) {
    candidate = `ws://${candidate.slice('http://'.length)}`;
  } else if (candidate.startsWith('https://')) {
    candidate = `wss://${candidate.slice('https://'.length)}`;
  } else if (!candidate.includes('://')) {
    candidate = `${fallbackScheme}://${candidate.replace(/^\/+/, '')}`;
  }

  try {
    const u = new URL(candidate);
    if (u.pathname === '' || u.pathname === '/') u.pathname = '/ws';
    return u.toString();
  } catch {
    return null;
  }
}

function buildDeviceFarmWsUrl(): string {
  const isSecure =
    typeof location !== 'undefined' && location.protocol === 'https:';
  const scheme = isSecure ? 'wss' : 'ws';

  const runtimeHost =
    typeof location !== 'undefined' ? location.hostname : 'localhost';
  const fallbackUrl = `${scheme}://${runtimeHost}:8081/ws`;

  const envUrl = process.env.NEXT_PUBLIC_DEVICE_FARM_WS_URL ?? '';
  const useEnv =
    envUrl.trim() !== '' &&
    !envUrl.includes('localhost') &&
    !envUrl.includes('127.0.0.1');
  const baseUrl = useEnv ? (normalizeWsUrl(envUrl, scheme) ?? fallbackUrl) : fallbackUrl;

  const authToken = tokenStorage.getAuthToken();
  return authToken && typeof window !== 'undefined'
    ? `${baseUrl}${baseUrl.includes('?') ? '&' : '?'}token=${encodeURIComponent(authToken)}`
    : baseUrl;
}

const listeners = new Set<(msg: WsMessage) => void>();

let sharedSocket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
let idleCloseTimer: ReturnType<typeof setTimeout> | undefined;

function broadcast(msg: WsMessage) {
  listeners.forEach((fn) => {
    try {
      fn(msg);
    } catch {
      // isolate subscriber errors
    }
  });
}

function handleTextMessage(raw: string) {
  try {
    const msg = JSON.parse(raw) as WsMessage;
    if (msg.type === 'frame' && 'jpeg_b64' in msg && msg.jpeg_b64 && 'serial' in msg) {
      const b64 = msg.jpeg_b64 as string;
      const rawBuf = atob(b64);
      const u8 = new Uint8Array(rawBuf.length);
      for (let i = 0; i < rawBuf.length; i++) u8[i] = rawBuf.charCodeAt(i);
      const legacy = msg as { device_width?: number; device_height?: number };
      FrameDispatcher.dispatch(msg.serial as string, {
        type: 'jpeg',
        data: u8,
        width: legacy.device_width ?? 1080,
        height: legacy.device_height ?? 1920,
      });
      return;
    }
    broadcast(msg);
  } catch {
    // ignore malformed messages
  }
}

function connectShared() {
  if (
    sharedSocket?.readyState === WebSocket.CONNECTING ||
    sharedSocket?.readyState === WebSocket.OPEN
  ) {
    return;
  }

  if (idleCloseTimer !== undefined) {
    clearTimeout(idleCloseTimer);
    idleCloseTimer = undefined;
  }

  const url = buildDeviceFarmWsUrl();
  const ws = new WebSocket(url);
  sharedSocket = ws;
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => {
    if (reconnectTimer !== undefined) {
      clearTimeout(reconnectTimer);
      reconnectTimer = undefined;
    }
    broadcast({ type: 'ws_status', connected: true });
  };

  ws.onclose = () => {
    sharedSocket = null;
    broadcast({ type: 'ws_status', connected: false });
    if (listeners.size > 0) {
      reconnectTimer = setTimeout(connectShared, 2000);
    }
  };

  ws.onerror = () => ws.close();

  ws.onmessage = (evt) => {
    if (evt.data instanceof ArrayBuffer) {
      const parsed = parseBinaryFrame(evt.data);
      if (parsed) FrameDispatcher.dispatch(parsed.serial, parsed.evt);
      return;
    }
    handleTextMessage(evt.data as string);
  };
}

function disconnectSharedIfIdle() {
  if (listeners.size > 0) return;
  // Debounce close: in dev/HMR/route transitions listeners can briefly drop to 0,
  // which would otherwise flap the WS connection and cause black-screen symptoms.
  if (idleCloseTimer !== undefined) return;
  idleCloseTimer = setTimeout(() => {
    idleCloseTimer = undefined;
    if (listeners.size > 0) return;
    if (reconnectTimer !== undefined) {
      clearTimeout(reconnectTimer);
      reconnectTimer = undefined;
    }
    sharedSocket?.close();
    sharedSocket = null;
  }, 800);
}

/** One browser-wide socket; multiple React trees/components share it. */
export function subscribeDeviceFarm(onMessage: (msg: WsMessage) => void): () => void {
  listeners.add(onMessage);
  if (listeners.size === 1) {
    connectShared();
  } else if (sharedSocket?.readyState === WebSocket.OPEN) {
    queueMicrotask(() => onMessage({ type: 'ws_status', connected: true }));
  }
  return () => {
    listeners.delete(onMessage);
    disconnectSharedIfIdle();
  };
}

export function createWs(onMessage: (msg: WsMessage) => void) {
  const unsubscribe = subscribeDeviceFarm(onMessage);
  return {
    send(obj: object) {
      if (sharedSocket?.readyState === WebSocket.OPEN) {
        sharedSocket.send(JSON.stringify(obj));
      }
    },
    close() {
      unsubscribe();
    },
  };
}
