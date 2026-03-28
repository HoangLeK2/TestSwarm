import type { WsMessage } from '../types';
import { tokenStorage } from '@/lib/token-storage';

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
let lastMessageTime = 0;

// Reconnect stale WebSocket on page focus (NAT timeout, server restart, etc.)
if (typeof window !== 'undefined') {
  window.addEventListener('focus', () => {
    if (listeners.size === 0) return;
    if (!sharedSocket || sharedSocket.readyState !== WebSocket.OPEN) {
      connectShared();
      return;
    }
    // If no message received in 10s, connection is likely stale
    if (Date.now() - lastMessageTime > 10_000) {
      sharedSocket.close(); // onclose handler triggers reconnect
    }
  });
}

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
    lastMessageTime = Date.now();
    if (typeof evt.data === 'string') {
      handleTextMessage(evt.data);
    }
    // Binary frames ignored — video is served via MJPEG HTTP endpoint
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
