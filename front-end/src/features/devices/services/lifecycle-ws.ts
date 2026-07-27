import { tokenStorage } from '@/lib/token-storage';
import {
  isLifecycleWsMessage,
  type LifecycleWsMessage
} from '../lib/lifecycle-events';

function normalizeWsOrigin(raw: string, fallbackScheme: 'ws' | 'wss') {
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
    u.pathname = '/ws/lifecycle';
    u.search = '';
    return u;
  } catch {
    return null;
  }
}

function buildLifecycleWsUrl(): string | null {
  const authToken = tokenStorage.getAuthToken();
  if (!authToken) return null;

  const isSecure =
    typeof location !== 'undefined' && location.protocol === 'https:';
  const scheme = isSecure ? 'wss' : 'ws';
  const runtimeHost =
    typeof location !== 'undefined' ? location.hostname : 'localhost';
  const fallbackOrigin = `${scheme}://${runtimeHost}:8081/ws`;

  const envUrl = process.env.NEXT_PUBLIC_DEVICE_FARM_WS_URL ?? '';
  const useEnv =
    envUrl.trim() !== '' &&
    !envUrl.includes('localhost') &&
    !envUrl.includes('127.0.0.1');
  const base = useEnv
    ? (normalizeWsOrigin(envUrl, scheme) ??
      normalizeWsOrigin(fallbackOrigin, scheme))
    : normalizeWsOrigin(fallbackOrigin, scheme);

  if (!base) return null;
  base.searchParams.set('token', authToken);
  return base.toString();
}

export type LifecycleWsHandle = {
  close: () => void;
};

const CONNECTING_CLOSE_TIMEOUT_MS = 5_000;

/**
 * Dedicated /ws/lifecycle connection (auth required). Separate from shared /ws
 * used for device streaming/control.
 */
export function connectLifecycleWs(
  onMessage: (msg: LifecycleWsMessage) => void,
  onConnectionChange?: (connected: boolean) => void
): LifecycleWsHandle {
  let closed = false;
  let socket: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let reconnectAttempt = 0;

  const closeSocket = (ws: WebSocket) => {
    ws.onmessage = null;
    ws.onerror = null;
    ws.onclose = null;

    if (ws.readyState === WebSocket.CONNECTING) {
      // Calling close() during CONNECTING emits a noisy browser warning. Let
      // the handshake settle, but retain a bounded fallback for a handshake
      // that never completes.
      let settled = false;

      const release = () => {
        if (settled) return;
        settled = true;
        clearTimeout(closeTimer);
        ws.onopen = null;
        ws.onerror = null;
        ws.onclose = null;
      };
      const close = () => {
        release();
        if (
          ws.readyState === WebSocket.CONNECTING ||
          ws.readyState === WebSocket.OPEN
        ) {
          ws.close();
        }
      };

      ws.onopen = close;
      ws.onerror = () => {};
      ws.onclose = release;
      const closeTimer = setTimeout(close, CONNECTING_CLOSE_TIMEOUT_MS);
      return;
    }

    ws.onopen = null;
    if (ws.readyState === WebSocket.OPEN) ws.close();
  };

  const scheduleReconnect = () => {
    if (closed) return;
    const delay = Math.min(30_000, 1000 * 2 ** reconnectAttempt);
    reconnectAttempt += 1;
    reconnectTimer = setTimeout(connect, delay);
  };

  const connect = () => {
    if (closed) return;
    const url = buildLifecycleWsUrl();
    if (!url) {
      onConnectionChange?.(false);
      return;
    }

    try {
      const ws = new WebSocket(url);
      socket = ws;

      ws.onopen = () => {
        if (closed || socket !== ws) {
          closeSocket(ws);
          return;
        }
        reconnectAttempt = 0;
        onConnectionChange?.(true);
      };

      ws.onmessage = (ev) => {
        if (closed || socket !== ws) return;
        try {
          const parsed: unknown = JSON.parse(String(ev.data));
          if (isLifecycleWsMessage(parsed)) {
            onMessage(parsed);
          }
        } catch {
          // ignore malformed frames
        }
      };

      ws.onclose = () => {
        if (socket !== ws) return;
        onConnectionChange?.(false);
        socket = null;
        if (!closed) scheduleReconnect();
      };

      // Browser WebSockets always follow an error with close. Reconnect from
      // onclose; calling close() here can hit a socket still CONNECTING.
      ws.onerror = () => {};
    } catch {
      scheduleReconnect();
      return;
    }
  };

  connect();

  return {
    close() {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      const activeSocket = socket;
      socket = null;
      if (activeSocket) closeSocket(activeSocket);
      onConnectionChange?.(false);
    }
  };
}
