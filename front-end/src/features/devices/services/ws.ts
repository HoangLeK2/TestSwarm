import type { WsMessage } from '../types';
import { tokenStorage } from '@/lib/token-storage';
import {
  shouldInvalidateCachedH264KeyForConfig,
  shouldReplayCachedKeyFrameAge
} from './h264-cache';
import { isCurrentTabNetworkActive } from '../lib/tab-network-activity';
import {
  DEVICE_FARM_WS_CLIENT_PING_INTERVAL_MS,
  isCurrentDeviceFarmWsEvent,
  nextReconnectDelayMs,
  shouldSendIdrRequest,
  shouldReconnectStaleSocketOnFocus
} from './ws-keepalive';
import {
  BinaryListenerRegistry,
  type BinaryListener
} from './binary-listener-registry';

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

function buildDeviceFarmWsUrl(options: { sessionIdSuffix?: string } = {}): string {
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
    const effectiveSessionId = options.sessionIdSuffix
      ? `${sessionId}:${options.sessionIdSuffix}`
      : sessionId;
    url += `${url.includes('?') ? '&' : '?'}session_id=${encodeURIComponent(effectiveSessionId)}`;
  }
  if (authToken && typeof window !== 'undefined') {
    url += `${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(authToken)}`;
  }
  return url;
}

const listeners = new Set<(msg: WsMessage) => void>();
const binaryListeners = new BinaryListenerRegistry();
const textDecoder =
  typeof TextDecoder !== 'undefined' ? new TextDecoder() : null;
const DEDICATED_MEDIA_WS_ENABLED =
  (process.env.NEXT_PUBLIC_DEVICE_FARM_DEDICATED_MEDIA_WS ?? '1').trim() !==
  '0';
const MEDIA_WS_IDLE_CLOSE_MS = Number(
  process.env.NEXT_PUBLIC_DEVICE_FARM_MEDIA_WS_IDLE_CLOSE_MS ?? 15_000
);

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
type MediaSocketEntry = {
  serial: string;
  socket: WebSocket | null;
  listeners: BinaryListenerRegistry;
  reconnectTimer?: ReturnType<typeof setTimeout>;
  idleCloseTimer?: ReturnType<typeof setTimeout>;
  reconnectAttempt: number;
  pendingIdr: boolean;
  watched: boolean;
};
const mediaSocketsBySerial = new Map<string, MediaSocketEntry>();

function flushPendingIdrRequests() {
  if (sharedSocket?.readyState !== WebSocket.OPEN) return;
  if (pendingIdrSerials.size === 0) return;
  const serials = Array.from(pendingIdrSerials);
  pendingIdrSerials.clear();
  serials.forEach((serial) => {
    // This request was never delivered. A recent timestamp from the previous
    // socket must not suppress the first recovery IDR on the replacement one.
    lastIdrRequestBySerial.delete(serial);
    requestIdr(serial, 0);
  });
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

function annexBPayloadContainsIdr(bytes: Uint8Array, offset: number): boolean {
  let start = -1;
  for (let i = offset; i < bytes.length; ) {
    let scLen = 0;
    if (
      i + 3 <= bytes.length &&
      bytes[i] === 0 &&
      bytes[i + 1] === 0 &&
      bytes[i + 2] === 1
    ) {
      scLen = 3;
    } else if (
      i + 4 <= bytes.length &&
      bytes[i] === 0 &&
      bytes[i + 1] === 0 &&
      bytes[i + 2] === 0 &&
      bytes[i + 3] === 1
    ) {
      scLen = 4;
    }
    if (scLen > 0) {
      if (
        start >= 0 &&
        start < i &&
        (bytes[start] & 0x1f) === 5 &&
        i - start > 1
      ) {
        return true;
      }
      start = i + scLen;
      i += scLen;
      continue;
    }
    i++;
  }
  return (
    start >= 0 &&
    start < bytes.length &&
    (bytes[start] & 0x1f) === 5 &&
    bytes.length - start > 1
  );
}

function isH264KeyFrame(buf: ArrayBuffer, slen: number): boolean {
  const doff = 2 + slen + 4;
  if (buf.byteLength <= doff + 9) return false;
  // Verify AVCC payload actually contains an IDR NAL (type 5). The wire
  // is_key flag alone is not trustworthy after stream restarts, and relay can
  // miss IDR when SPS/PPS/AUD NALs precede the slice.
  let offset = doff + 9;
  const bytes = new Uint8Array(buf);
  let avccValid = false;
  let avccHasIdr = false;
  const avccStart = offset;
  while (offset + 4 <= bytes.length) {
    const len =
      ((bytes[offset] << 24) |
        (bytes[offset + 1] << 16) |
        (bytes[offset + 2] << 8) |
        bytes[offset + 3]) >>>
      0;
    if (len === 0 || offset + 4 + len > bytes.length) {
      avccValid = false;
      break;
    }
    const nalType = bytes[offset + 4] & 0x1f;
    if (nalType === 5 && len > 1) avccHasIdr = true;
    offset += 4 + len;
  }
  avccValid = offset === bytes.length && offset > avccStart;
  if (avccValid) return avccHasIdr;
  if (
    (avccStart + 3 <= bytes.length &&
      bytes[avccStart] === 0 &&
      bytes[avccStart + 1] === 0 &&
      bytes[avccStart + 2] === 1) ||
    (avccStart + 4 <= bytes.length &&
      bytes[avccStart] === 0 &&
      bytes[avccStart + 1] === 0 &&
      bytes[avccStart + 2] === 0 &&
      bytes[avccStart + 3] === 1)
  ) {
    return annexBPayloadContainsIdr(bytes, avccStart);
  }
  return false;
}

function handleBinaryFrame(
  buf: ArrayBuffer,
  registry: BinaryListenerRegistry
): void {
  let parsedSerial: string | null = null;
  // Always cache H264 config frames (0x10) for late-arriving binary listeners.
  // The WS text listener connects first (for device status); the H264 hook
  // mounts later. Without caching, the bootstrap config frame arrives when
  // binaryListeners is empty and is silently dropped — decoder never initialises.
  if (buf.byteLength >= 3) {
    const view = new DataView(buf);
    const ft = view.getUint8(0);
    const slen = view.getUint8(1);
    if (slen > 0 && buf.byteLength >= 2 + slen) {
      parsedSerial = decodeSerial(buf, slen);
      if (ft === 0x10) {
        if (
          shouldInvalidateCachedH264KeyForConfig(
            lastConfigBySerial.get(parsedSerial),
            buf
          )
        ) {
          lastKeyBySerial.delete(parsedSerial);
          lastKeyTsBySerial.delete(parsedSerial);
          waitForKeyBySerial.add(parsedSerial);
        }
        // Keep cache ownership stable: listeners may transfer incoming buffers
        // to workers, which detaches them.
        lastConfigBySerial.set(parsedSerial, buf.slice(0));
      } else if (ft === 0x11) {
        // Cache keyframes so late-subscribing jmuxer hooks get an IDR immediately
        // instead of waiting up to 14 s for the next one.
        if (isH264KeyFrame(buf, slen)) {
          // Same ownership rule as config cache above.
          lastKeyBySerial.set(parsedSerial, buf.slice(0));
          lastKeyTsBySerial.set(parsedSerial, Date.now());
          waitForKeyBySerial.delete(parsedSerial);
        } else if (waitForKeyBySerial.has(parsedSerial)) {
          return;
        }
      }
    }
  }
  if (registry.size > 0) {
    if (parsedSerial === null && buf.byteLength >= 3) {
      const view = new DataView(buf);
      const slen = view.getUint8(1);
      if (slen > 0 && buf.byteLength >= 2 + slen) {
        parsedSerial = decodeSerial(buf, slen);
      }
    }
    registry.dispatch(buf, parsedSerial);
  }
}

// Reconnect stale WebSocket on page focus (NAT timeout, server restart, etc.)
if (typeof window !== 'undefined') {
  window.addEventListener('visibilitychange', () => {
    if (!isCurrentTabNetworkActive()) {
      // Keep the shared socket warm while a control stream is active. Chrome can
      // briefly report hidden during tab switches, DevTools focus changes, and
      // page lifecycle transitions; closing here tears down watch_serial and
      // causes scrcpy attach/detach churn. Real page unload is handled by the
      // DeviceScreen pagehide detach path.
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

function sendPongOnSocket(socket: WebSocket | null, ts: unknown) {
  if (socket?.readyState !== WebSocket.OPEN) return;
  const payload: { type: 'pong'; ts?: number } = { type: 'pong' };
  if (typeof ts === 'number') payload.ts = ts;
  try {
    socket.send(JSON.stringify(payload));
  } catch {
    // socket may be closing; the normal onclose path reconnects
  }
}

function sendPong(ts: unknown) {
  sendPongOnSocket(sharedSocket, ts);
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

function getOrCreateMediaSocketEntry(serial: string): MediaSocketEntry {
  let entry = mediaSocketsBySerial.get(serial);
  if (!entry) {
    entry = {
      serial,
      socket: null,
      listeners: new BinaryListenerRegistry(),
      reconnectAttempt: 0,
      pendingIdr: false,
      watched: false
    };
    mediaSocketsBySerial.set(serial, entry);
  }
  return entry;
}

function sendMediaJson(entry: MediaSocketEntry, payload: object): boolean {
  if (entry.socket?.readyState !== WebSocket.OPEN) return false;
  try {
    entry.socket.send(JSON.stringify(payload));
    return true;
  } catch {
    return false;
  }
}

function sendMediaWatchSerial(entry: MediaSocketEntry, force = false): void {
  if (!force && entry.watched) return;
  if (sendMediaJson(entry, { type: 'watch_serial', serial: entry.serial })) {
    entry.watched = true;
  }
}

function connectMediaSocket(entry: MediaSocketEntry): void {
  if (!isCurrentTabNetworkActive()) return;
  if (
    entry.socket?.readyState === WebSocket.CONNECTING ||
    entry.socket?.readyState === WebSocket.OPEN
  ) {
    return;
  }
  if (entry.reconnectTimer !== undefined) {
    clearTimeout(entry.reconnectTimer);
    entry.reconnectTimer = undefined;
  }
  const ws = new WebSocket(
    buildDeviceFarmWsUrl({ sessionIdSuffix: `media:${entry.serial}` })
  );
  entry.socket = ws;
  entry.watched = false;
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => {
    if (entry.socket !== ws) {
      try {
        ws.close();
      } catch {
        // stale media socket
      }
      return;
    }
    entry.reconnectAttempt = 0;
    sendMediaWatchSerial(entry, true);
    if (entry.pendingIdr) {
      entry.pendingIdr = false;
      sendMediaJson(entry, { type: 'request_idr', serial: entry.serial });
    }
  };

  ws.onclose = () => {
    if (entry.socket !== ws) return;
    entry.socket = null;
    entry.watched = false;
    if (entry.listeners.size > 0 && isCurrentTabNetworkActive()) {
      const delay = nextReconnectDelayMs(entry.reconnectAttempt);
      entry.reconnectAttempt += 1;
      entry.reconnectTimer = setTimeout(() => connectMediaSocket(entry), delay);
      return;
    }
    if (entry.listeners.size === 0) {
      mediaSocketsBySerial.delete(entry.serial);
    }
  };

  ws.onerror = () => {
    if (entry.socket !== ws) return;
    ws.close();
  };

  ws.onmessage = (evt) => {
    if (entry.socket !== ws) return;
    if (typeof evt.data === 'string') {
      try {
        const parsed = JSON.parse(evt.data) as unknown;
        if (
          parsed &&
          typeof parsed === 'object' &&
          'type' in parsed &&
          (parsed as { type?: unknown }).type === 'ping'
        ) {
          sendPongOnSocket(ws, (parsed as { ts?: unknown }).ts);
        }
      } catch {
        // media socket ignores malformed text/control messages
      }
      return;
    }
    if (evt.data instanceof ArrayBuffer) {
      handleBinaryFrame(evt.data as ArrayBuffer, entry.listeners);
    }
  };
}

function scheduleMediaSocketIdleClose(entry: MediaSocketEntry): void {
  if (entry.idleCloseTimer !== undefined) {
    clearTimeout(entry.idleCloseTimer);
  }
  entry.idleCloseTimer = setTimeout(() => {
    entry.idleCloseTimer = undefined;
    if (entry.listeners.size > 0) return;
    sendMediaJson(entry, { type: 'unwatch_serial', serial: entry.serial });
    try {
      entry.socket?.close();
    } catch {
      // ignore close failure
    }
    entry.socket = null;
    entry.watched = false;
    mediaSocketsBySerial.delete(entry.serial);
  }, Math.max(0, MEDIA_WS_IDLE_CLOSE_MS));
}

function subscribeMediaBinaryFrames(
  onBinary: (buf: ArrayBuffer) => void,
  serial: string
): () => void {
  const entry = getOrCreateMediaSocketEntry(serial);
  if (entry.idleCloseTimer !== undefined) {
    clearTimeout(entry.idleCloseTimer);
    entry.idleCloseTimer = undefined;
  }
  const listener: BinaryListener = { fn: onBinary, serial };
  entry.listeners.add(listener);
  connectMediaSocket(entry);
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
  return () => {
    entry.listeners.delete(listener);
    if (entry.listeners.size === 0) {
      scheduleMediaSocketIdleClose(entry);
    }
  };
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
      handleBinaryFrame(evt.data as ArrayBuffer, binaryListeners);
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
  if (serial && DEDICATED_MEDIA_WS_ENABLED) {
    return subscribeMediaBinaryFrames(onBinary, serial);
  }
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

export function clearH264Cache(serial: string): void {
  lastConfigBySerial.delete(serial);
  lastKeyBySerial.delete(serial);
  lastKeyTsBySerial.delete(serial);
  waitForKeyBySerial.add(serial);
}

export function discardCachedH264KeyFrame(serial: string): void {
  lastKeyBySerial.delete(serial);
  lastKeyTsBySerial.delete(serial);
  waitForKeyBySerial.add(serial);
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
  const now = Date.now();
  const last = lastIdrRequestBySerial.get(serial) ?? 0;
  if (!shouldSendIdrRequest(last, now, minIntervalMs)) return;
  const mediaEntry = mediaSocketsBySerial.get(serial);
  if (
    DEDICATED_MEDIA_WS_ENABLED &&
    mediaEntry &&
    mediaEntry.listeners.size > 0
  ) {
    if (mediaEntry.socket?.readyState === WebSocket.OPEN) {
      if (
        sendMediaJson(mediaEntry, {
          type: 'request_idr',
          serial
        })
      ) {
        lastIdrRequestBySerial.set(serial, now);
        return;
      }
    }
    mediaEntry.pendingIdr = true;
    lastIdrRequestBySerial.set(serial, now);
    connectMediaSocket(mediaEntry);
    return;
  }
  ensureWatchSerial(serial);
  if (sharedSocket?.readyState === WebSocket.OPEN) {
    try {
      lastIdrRequestBySerial.set(serial, now);
      sharedSocket.send(JSON.stringify({ type: 'request_idr', serial }));
    } catch {
      lastIdrRequestBySerial.delete(serial);
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
