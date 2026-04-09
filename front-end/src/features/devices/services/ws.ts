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
  let url = baseUrl;
  if (typeof window !== 'undefined') {
    const key = 'devicefarm_ws_session_id';
    let sessionId = window.sessionStorage.getItem(key);
    if (!sessionId) {
      sessionId = (typeof crypto !== 'undefined' && 'randomUUID' in crypto)
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      window.sessionStorage.setItem(key, sessionId);
    }
    url += `${url.includes('?') ? '&' : '?'}session_id=${encodeURIComponent(sessionId)}`;
  }
  if (authToken && typeof window !== 'undefined') {
    url += `${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(authToken)}`;
  }
  return url;
}

const listeners = new Set<(msg: WsMessage) => void>();
type BinaryListener = { fn: (buf: ArrayBuffer) => void; serial?: string };
const binaryListeners = new Set<BinaryListener>();

// Cache last H264 config frame (0x10) per serial so late-arriving binary listeners
// (hooks that mount after the WS was already open) get the SPS/PPS immediately.
const lastConfigBySerial = new Map<string, ArrayBuffer>();

// Cache last H264 keyframe (0x11 is_key=1) per serial.
// Without this, late subscribers (jmuxer hook mounting after WS bootstrap) must
// wait up to 14 s for the next IDR before video appears. Caching the last IDR
// lets us replay it immediately so jmuxer can initialise the SourceBuffer at once.
const lastKeyBySerial = new Map<string, ArrayBuffer>();

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
    // Don't force-close too aggressively: low-FPS periods can legitimately exceed
    // 10s without traffic and this creates reconnect churn (visible stutter).
    if (Date.now() - lastMessageTime > 45_000) {
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
    lastConfigBySerial.clear();
    lastKeyBySerial.clear(); // stale after disconnect — server will re-send bootstrap on reconnect
    broadcast({ type: 'ws_status', connected: false });
    if (listeners.size > 0 || binaryListeners.size > 0) {
      reconnectTimer = setTimeout(connectShared, 2000);
    }
  };

  ws.onerror = () => ws.close();

  ws.onmessage = (evt) => {
    lastMessageTime = Date.now();
    if (typeof evt.data === 'string') {
      handleTextMessage(evt.data);
    } else if (evt.data instanceof ArrayBuffer) {
      const buf = evt.data as ArrayBuffer;
      // Always cache H264 config frames (0x10) for late-arriving binary listeners.
      // The WS text listener connects first (for device status); the H264 hook
      // mounts later. Without caching, the bootstrap config frame arrives when
      // binaryListeners is empty and is silently dropped — decoder never initialises.
      if (buf.byteLength >= 3) {
        const view = new DataView(buf);
        const ft = view.getUint8(0);
        const slen = view.getUint8(1);
        if (slen > 0 && buf.byteLength >= 2 + slen) {
          const serial = new TextDecoder().decode(new Uint8Array(buf, 2, slen));
          if (ft === 0x10) {
            // Keep cache ownership stable: listeners may transfer incoming buffers
            // to workers, which detaches them.
            lastConfigBySerial.set(serial, buf.slice(0));
          } else if (ft === 0x11) {
            // Cache keyframes so late-subscribing jmuxer hooks get an IDR immediately
            // instead of waiting up to 14 s for the next one.
            const doff = 2 + slen + 4; // skip serial + w/h
            if (buf.byteLength > doff && view.getUint8(doff) !== 0) { // is_key=1
              // Same ownership rule as config cache above.
              lastKeyBySerial.set(serial, buf.slice(0));
            }
          }
        }
      }
      if (binaryListeners.size > 0) {
        let parsedSerial: string | null = null;
        if (buf.byteLength >= 3) {
          const view = new DataView(buf);
          const slen = view.getUint8(1);
          if (slen > 0 && buf.byteLength >= 2 + slen) {
            parsedSerial = new TextDecoder().decode(new Uint8Array(buf, 2, slen));
          }
        }
        binaryListeners.forEach(({ fn, serial }) => {
          try {
            if (serial && parsedSerial && serial !== parsedSerial) return;
            fn(buf);
          } catch {
            // isolate subscriber errors
          }
        });
      }
    }
  };
}

function disconnectSharedIfIdle() {
  if (listeners.size > 0 || binaryListeners.size > 0) return;
  // Keep socket warm to avoid rapid close/reopen flapping during React remounts,
  // route transitions, and hook re-subscriptions.
  if (reconnectTimer !== undefined) {
    clearTimeout(reconnectTimer);
    reconnectTimer = undefined;
  }
}

/**
 * Subscribe to raw binary frames from the server (H264 config 0x10 + video 0x11 + JPEG 0x01).
 * Frame layout: [type:1B][slen:1B][serial:slen][w:2B BE][h:2B BE][payload...]
 * Returns unsubscribe function.
 */
export function subscribeBinaryFrames(
  onBinary: (buf: ArrayBuffer) => void,
  serial?: string
): () => void {
  const listener: BinaryListener = { fn: onBinary, serial };
  binaryListeners.add(listener);
  // Replay cached config + keyframe so late-arriving hooks (common case: hook
  // mounts after WS bootstrap) get both SPS/PPS and an IDR immediately.
  // config must come before keyframe so the decoder can initialise.
  if (serial) {
    const cfg = lastConfigBySerial.get(serial);
    const key = lastKeyBySerial.get(serial);
    const toReplay: ArrayBuffer[] = [];
    if (cfg) toReplay.push(cfg);
    if (key) toReplay.push(key);
    if (toReplay.length > 0) {
      queueMicrotask(() => {
        toReplay.forEach((frame) => {
          try {
            onBinary(frame.slice(0));
          } catch {
            // isolate subscriber errors
          }
        });
      });
    }
  } else if (lastConfigBySerial.size > 0 || lastKeyBySerial.size > 0) {
    const serials = new Set([...Array.from(lastConfigBySerial.keys()), ...Array.from(lastKeyBySerial.keys())]);
    const toReplay: ArrayBuffer[] = [];
    serials.forEach((serial) => {
      const cfg = lastConfigBySerial.get(serial);
      const key = lastKeyBySerial.get(serial);
      if (cfg) toReplay.push(cfg);
      if (key) toReplay.push(key);
    });
    queueMicrotask(() => {
      toReplay.forEach((frame) => {
        try {
          // Replay a fresh copy because subscribers may transfer ownership.
          onBinary(frame.slice(0));
        } catch {
          // isolate subscriber errors
        }
      });
    });
  }
  if (listeners.size === 0 && binaryListeners.size === 1) {
    connectShared();
  }
  return () => {
    binaryListeners.delete(listener);
    if (listeners.size === 0) disconnectSharedIfIdle();
  };
}

/**
 * Return the last cached H264 config frame (0x10) for a given device serial,
 * or undefined if none has been received yet. Used by useH264Video to replay
 * the cached config immediately after the worker is reset (e.g. serial change).
 */
export function getLastConfigFrame(serial: string): ArrayBuffer | undefined {
  return lastConfigBySerial.get(serial) ?? undefined;
}

export function getLastKeyFrame(serial: string): ArrayBuffer | undefined {
  return lastKeyBySerial.get(serial) ?? undefined;
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
