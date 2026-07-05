import type { WsMessage } from '../types';
import { tokenStorage } from '@/lib/token-storage';
import { shouldReplayCachedKeyFrameAge } from './h264-cache';
import { isCurrentTabNetworkActive } from '../lib/tab-network-activity';
import {
  DEVICE_FARM_WS_CLIENT_PING_INTERVAL_MS,
  isCurrentDeviceFarmWsEvent,
  nextReconnectDelayMs,
  shouldReconnectStaleSocketOnFocus
} from './ws-keepalive';

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
  const baseUrl = useEnv
    ? (normalizeWsUrl(envUrl, scheme) ?? fallbackUrl)
    : fallbackUrl;

  const authToken = tokenStorage.getAuthToken();
  let url = baseUrl;
  if (typeof window !== 'undefined') {
    const key = 'devicefarm_ws_session_id';
    let sessionId = window.sessionStorage.getItem(key);
    if (!sessionId) {
      sessionId =
        typeof crypto !== 'undefined' && 'randomUUID' in crypto
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
const textDecoder =
  typeof TextDecoder !== 'undefined' ? new TextDecoder() : null;

// Cache last H264 config frame (0x10) per serial so late-arriving binary listeners
// (hooks that mount after the WS was already open) get the SPS/PPS immediately.
const lastConfigBySerial = new Map<string, ArrayBuffer>();

// Cache last H264 keyframe (0x11 is_key=1) per serial.
// Without this, late subscribers (jmuxer hook mounting after WS bootstrap) must
// wait up to 14 s for the next IDR before video appears. Caching the last IDR
// lets us replay it immediately so jmuxer can initialise the SourceBuffer at once.
const lastKeyBySerial = new Map<string, ArrayBuffer>();
const lastKeyTsBySerial = new Map<string, number>();
const waitForKeyBySerial = new Set<string>();
// Keyframes older than this are considered stale. Replaying a stale IDR while
// live P-frames reference a newer one (arrived while tab hidden) drifts the
// decoder into a black state. Skip replay when stale � server-side forced IDR
// fills the gap within ~100ms.
let sharedSocket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
let idleCloseTimer: ReturnType<typeof setTimeout> | undefined;
let clientHeartbeatTimer: ReturnType<typeof setInterval> | undefined;
let lastMessageTime = 0;
let lastForcedReconnectAt = 0;
let reconnectAttempt = 0;
const lastIdrRequestBySerial = new Map<string, number>();
// Backend can spawn per-serial sender tasks on demand. Track refs so we only
// watch serials that at least one component is decoding.
const watchRefCountBySerial = new Map<string, number>();
const watchedSerialsOnSocket = new Set<string>();
const WATCH_SERIAL_UNWATCH_DEBOUNCE_MS = 15_000;
const pendingUnwatchTimersBySerial = new Map<
  string,
  ReturnType<typeof setTimeout>
>();
const pendingIdrSerials = new Set<string>();
type WsReadyCallback = () => void;
const wsReadyQueue: WsReadyCallback[] = [];

function flushPendingIdrRequests() {
  if (sharedSocket?.readyState !== WebSocket.OPEN) return;
  if (pendingIdrSerials.size === 0) return;
  const serials = Array.from(pendingIdrSerials);
  pendingIdrSerials.clear();
  serials.forEach((serial) => requestIdr(serial, 0));
}

function flushWsReadyQueue() {
  if (sharedSocket?.readyState !== WebSocket.OPEN) return;
  const queued = wsReadyQueue.splice(0);
  queued.forEach((fn) => {
    try {
      fn();
    } catch {
      // isolate subscriber errors
    }
  });
}

/** Run callback once the shared socket is open (now or on next onopen). */
export function runWhenDeviceFarmWsOpen(fn: () => void): () => void {
  if (sharedSocket?.readyState === WebSocket.OPEN) {
    queueMicrotask(() => {
      try {
        fn();
      } catch {
        // isolate subscriber errors
      }
    });
    return () => {};
  }
  wsReadyQueue.push(fn);
  if (
    !sharedSocket ||
    sharedSocket.readyState === WebSocket.CLOSED ||
    sharedSocket.readyState === WebSocket.CLOSING
  ) {
    connectShared();
  }
  return () => {
    const idx = wsReadyQueue.indexOf(fn);
    if (idx >= 0) wsReadyQueue.splice(idx, 1);
  };
}

function decodeSerial(buf: ArrayBuffer, slen: number): string {
  if (!textDecoder || slen <= 0 || buf.byteLength < 2 + slen) return '';
  return textDecoder.decode(new Uint8Array(buf, 2, slen));
}

function isH264KeyFrame(
  view: DataView,
  buf: ArrayBuffer,
  slen: number
): boolean {
  const doff = 2 + slen + 4;
  return buf.byteLength > doff && view.getUint8(doff) !== 0;
}

// Reconnect stale WebSocket on page focus (NAT timeout, server restart, etc.)
if (typeof window !== 'undefined') {
  window.addEventListener('visibilitychange', () => {
    if (!isCurrentTabNetworkActive()) {
      if (
        sharedSocket?.readyState === WebSocket.OPEN ||
        sharedSocket?.readyState === WebSocket.CONNECTING
      ) {
        sharedSocket.close();
      }
      return;
    }
    if (
      (listeners.size > 0 || binaryListeners.size > 0) &&
      (!sharedSocket ||
        sharedSocket.readyState === WebSocket.CLOSED ||
        sharedSocket.readyState === WebSocket.CLOSING)
    ) {
      connectShared();
    }
  });

  window.addEventListener('focus', () => {
    if (!isCurrentTabNetworkActive()) return;
    if (listeners.size === 0 && binaryListeners.size === 0) return;
    if (!sharedSocket || sharedSocket.readyState !== WebSocket.OPEN) {
      connectShared();
      return;
    }
    if (binaryListeners.size > 0) return;
    // Don't force-close too aggressively: low-FPS periods can legitimately exceed
    // 10s without traffic and this creates reconnect churn (visible stutter).
    if (shouldReconnectStaleSocketOnFocus(lastMessageTime)) {
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

function sendPong(ts: unknown) {
  if (sharedSocket?.readyState !== WebSocket.OPEN) return;
  const payload: { type: 'pong'; ts?: number } = { type: 'pong' };
  if (typeof ts === 'number') payload.ts = ts;
  try {
    sharedSocket.send(JSON.stringify(payload));
  } catch {
    // socket may be closing; the normal onclose path reconnects
  }
}

function sendPing() {
  if (sharedSocket?.readyState !== WebSocket.OPEN) return;
  if (listeners.size === 0 && binaryListeners.size === 0) return;
  try {
    sharedSocket.send(JSON.stringify({ type: 'ping', ts: Date.now() }));
  } catch {
    // socket may be closing; the normal onclose path reconnects
  }
}

function stopClientHeartbeat() {
  if (clientHeartbeatTimer !== undefined) {
    clearInterval(clientHeartbeatTimer);
    clientHeartbeatTimer = undefined;
  }
}

function startClientHeartbeat() {
  stopClientHeartbeat();
  clientHeartbeatTimer = setInterval(
    sendPing,
    DEVICE_FARM_WS_CLIENT_PING_INTERVAL_MS
  );
}

function handleTextMessage(raw: string) {
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed &&
      typeof parsed === 'object' &&
      'type' in parsed &&
      (parsed as { type?: unknown }).type === 'ping'
    ) {
      sendPong((parsed as { ts?: unknown }).ts);
      return;
    }
    broadcast(parsed as WsMessage);
  } catch {
    // ignore malformed messages
  }
}

function sendWatchSerial(serial: string, force = false) {
  if (!serial || sharedSocket?.readyState !== WebSocket.OPEN) return;
  if (!force && watchedSerialsOnSocket.has(serial)) return;
  try {
    sharedSocket.send(JSON.stringify({ type: 'watch_serial', serial }));
    watchedSerialsOnSocket.add(serial);
  } catch {
    // socket may be closing; onopen will re-assert watches
  }
}

function clearPendingUnwatch(serial: string) {
  const timer = pendingUnwatchTimersBySerial.get(serial);
  if (timer === undefined) return;
  clearTimeout(timer);
  pendingUnwatchTimersBySerial.delete(serial);
}

function scheduleUnwatchSerial(serial: string) {
  clearPendingUnwatch(serial);
  pendingUnwatchTimersBySerial.set(
    serial,
    setTimeout(() => {
      pendingUnwatchTimersBySerial.delete(serial);
      if ((watchRefCountBySerial.get(serial) ?? 0) > 0) return;
      watchedSerialsOnSocket.delete(serial);
      if (sharedSocket?.readyState !== WebSocket.OPEN) return;
      try {
        sharedSocket.send(JSON.stringify({ type: 'unwatch_serial', serial }));
      } catch {
        // ignore; socket may be closing
      }
    }, WATCH_SERIAL_UNWATCH_DEBOUNCE_MS)
  );
}

/** Re-assert watch_serial when a viewer is active (idempotent on server). */
export function ensureWatchSerial(serial: string) {
  if (!serial) return;
  const prev = watchRefCountBySerial.get(serial) ?? 0;
  if (prev <= 0) return;
  if (
    !sharedSocket ||
    sharedSocket.readyState === WebSocket.CLOSED ||
    sharedSocket.readyState === WebSocket.CLOSING
  ) {
    connectShared();
    return;
  }
  sendWatchSerial(serial, true);
}

function connectShared() {
  if (!isCurrentTabNetworkActive()) return;
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
    if (!isCurrentDeviceFarmWsEvent(sharedSocket, ws)) {
      try {
        ws.close();
      } catch {
        // stale socket; current socket owns reconnect state
      }
      return;
    }
    lastMessageTime = Date.now();
    reconnectAttempt = 0;
    if (reconnectTimer !== undefined) {
      clearTimeout(reconnectTimer);
      reconnectTimer = undefined;
    }
    startClientHeartbeat();
    // Re-assert watched serials after reconnect.
    watchedSerialsOnSocket.clear();
    watchRefCountBySerial.forEach((_count, serial) => {
      sendWatchSerial(serial, true);
    });
    flushPendingIdrRequests();
    flushWsReadyQueue();
    broadcast({ type: 'ws_status', connected: true });
  };

  ws.onclose = () => {
    if (!isCurrentDeviceFarmWsEvent(sharedSocket, ws)) return;
    stopClientHeartbeat();
    sharedSocket = null;
    watchedSerialsOnSocket.clear();
    lastConfigBySerial.clear();
    lastKeyBySerial.clear(); // stale after disconnect � server will re-send bootstrap on reconnect
    lastKeyTsBySerial.clear();
    broadcast({ type: 'ws_status', connected: false });
    if (
      isCurrentTabNetworkActive() &&
      (listeners.size > 0 || binaryListeners.size > 0)
    ) {
      if (reconnectTimer !== undefined) {
        clearTimeout(reconnectTimer);
        reconnectTimer = undefined;
      }
      const delay = nextReconnectDelayMs(reconnectAttempt);
      reconnectAttempt += 1;
      reconnectTimer = setTimeout(connectShared, delay);
    }
  };

  ws.onerror = () => {
    if (!isCurrentDeviceFarmWsEvent(sharedSocket, ws)) return;
    ws.close();
  };

  ws.onmessage = (evt) => {
    if (!isCurrentDeviceFarmWsEvent(sharedSocket, ws)) return;
    lastMessageTime = Date.now();
    if (typeof evt.data === 'string') {
      handleTextMessage(evt.data);
    } else if (evt.data instanceof ArrayBuffer) {
      const buf = evt.data as ArrayBuffer;
      // Always cache H264 config frames (0x10) for late-arriving binary listeners.
      // The WS text listener connects first (for device status); the H264 hook
      // mounts later. Without caching, the bootstrap config frame arrives when
      // binaryListeners is empty and is silently dropped � decoder never initialises.
      if (buf.byteLength >= 3) {
        const view = new DataView(buf);
        const ft = view.getUint8(0);
        const slen = view.getUint8(1);
        if (slen > 0 && buf.byteLength >= 2 + slen) {
          const serial = decodeSerial(buf, slen);
          if (ft === 0x10) {
            // Keep cache ownership stable: listeners may transfer incoming buffers
            // to workers, which detaches them.
            lastConfigBySerial.set(serial, buf.slice(0));
          } else if (ft === 0x11) {
            // Cache keyframes so late-subscribing jmuxer hooks get an IDR immediately
            // instead of waiting up to 14 s for the next one.
            if (isH264KeyFrame(view, buf, slen)) {
              // Same ownership rule as config cache above.
              lastKeyBySerial.set(serial, buf.slice(0));
              lastKeyTsBySerial.set(serial, Date.now());
              waitForKeyBySerial.delete(serial);
            } else if (waitForKeyBySerial.has(serial)) {
              return;
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
            parsedSerial = decodeSerial(buf, slen);
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
  if (serial) {
    clearPendingUnwatch(serial);
    const prev = watchRefCountBySerial.get(serial) ?? 0;
    watchRefCountBySerial.set(serial, prev + 1);
    if (prev === 0) {
      sendWatchSerial(serial);
    }
  }
  if (
    !sharedSocket ||
    sharedSocket.readyState === WebSocket.CLOSED ||
    sharedSocket.readyState === WebSocket.CLOSING
  ) {
    connectShared();
  }
  // Replay cached config + keyframe so late-arriving hooks (common case: hook
  // mounts after WS bootstrap) get both SPS/PPS and an IDR immediately.
  // config must come before keyframe so the decoder can initialise.
  if (serial) {
    const cfg = lastConfigBySerial.get(serial);
    const key = isCachedKeyFrameStale(serial)
      ? undefined
      : lastKeyBySerial.get(serial);
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
    const serials = new Set([
      ...Array.from(lastConfigBySerial.keys()),
      ...Array.from(lastKeyBySerial.keys())
    ]);
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
    if (serial) {
      const prev = watchRefCountBySerial.get(serial) ?? 0;
      const next = Math.max(0, prev - 1);
      if (next === 0) {
        watchRefCountBySerial.delete(serial);
        scheduleUnwatchSerial(serial);
      } else {
        watchRefCountBySerial.set(serial, next);
      }
    }
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

/**
 * Age of the cached keyframe for a serial in ms. Returns Infinity if no key
 * cached. Callers should treat values > STALE_KEY_MS as unsafe to replay.
 */
export function getLastKeyFrameAge(serial: string): number {
  const ts = lastKeyTsBySerial.get(serial);
  if (ts === undefined) return Infinity;
  return Date.now() - ts;
}

export function isCachedKeyFrameStale(serial: string): boolean {
  return !shouldReplayCachedKeyFrameAge(getLastKeyFrameAge(serial));
}

/**
 * Ask the server to force an IDR (keyframe) from the given device. Used on
 * mount / reconnect / visibility return so the browser decoder recovers in
 * ~100ms instead of waiting up to ~14s for the next natural keyframe.
 */
export function requestIdr(serial: string, minIntervalMs = 700): void {
  if (!serial) return;
  ensureWatchSerial(serial);
  const now = Date.now();
  const last = lastIdrRequestBySerial.get(serial) ?? 0;
  if (minIntervalMs > 0 && now - last < minIntervalMs) return;
  if (sharedSocket?.readyState === WebSocket.OPEN) {
    try {
      lastIdrRequestBySerial.set(serial, now);
      sharedSocket.send(JSON.stringify({ type: 'request_idr', serial }));
    } catch {
      pendingIdrSerials.add(serial);
    }
    return;
  }
  pendingIdrSerials.add(serial);
  if (
    !sharedSocket ||
    sharedSocket.readyState === WebSocket.CLOSED ||
    sharedSocket.readyState === WebSocket.CLOSING
  ) {
    connectShared();
  }
}

export function notifyDecoderBackpressure(
  serial: string,
  minIntervalMs = 500
): void {
  if (!serial) return;
  waitForKeyBySerial.add(serial);
  requestIdr(serial, minIntervalMs);
}

export function reconnectDeviceFarmSocket(reason = 'stream_recovery'): void {
  const now = Date.now();
  if (now - lastForcedReconnectAt < 30_000) return;
  lastForcedReconnectAt = now;
  if (
    sharedSocket?.readyState === WebSocket.OPEN ||
    sharedSocket?.readyState === WebSocket.CONNECTING
  ) {
    try {
      console.debug('[DeviceFarm WS] forced reconnect:', reason);
      sharedSocket.close();
      return;
    } catch {
      sharedSocket = null;
    }
  }
  console.debug('[DeviceFarm WS] forced reconnect:', reason);
  if (listeners.size > 0 || binaryListeners.size > 0) {
    connectShared();
  }
}

/** One browser-wide socket; multiple React trees/components share it. */
export function subscribeDeviceFarm(
  onMessage: (msg: WsMessage) => void
): () => void {
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
    }
  };
}
