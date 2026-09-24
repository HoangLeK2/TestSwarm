/**
 * Media-progress stall detection for the WebRTC viewer path.
 *
 * The H264/WebSocket path has had a freeze watchdog for a long time
 * (use-h264-canvas.ts: a 1s tick that resets WebCodecs and asks for a fresh
 * IDR). The WebRTC path had nothing at all, and that is the whole reason a
 * frozen stream needed a page refresh: a RTCPeerConnection can sit in
 * `connected` forever while no byte and no frame moves, and nothing in the
 * browser, the backend or the adapter was watching the counters.
 *
 * Connection state is not evidence of media. `pc.connectionState === 'connected'`
 * says ICE and DTLS are up, nothing more. Progress is measured from the
 * inbound-rtp counters and from those alone.
 *
 * Why the picture cannot come back on its own today: the deployed transport is
 * RTSP push (media-adapter -> go2rtc :8554). RTSP has no back-channel for a
 * receiver to report picture loss, so a browser PLI dies at go2rtc and never
 * reaches the phone — see rtspSink in
 * agent-boot/media-adapter/internal/adapters/outbound/rtspserver/remote_sink.go.
 * The only thing on the far side that asks scrcpy for an IDR on a viewer's
 * behalf is the attach burst in controlplane/client.go startSession.
 *
 * A stall report therefore has two possible answers, and the caller picks by
 * reason. `decoder_stalled` means bytes are arriving and nothing decodes — a
 * broken reference chain, which POST .../keyframe repairs in about 100ms with
 * the connection intact (then `resume()` re-arms this watcher to see whether it
 * worked). Anything else means no media at all, where a keyframe has nothing to
 * travel over, and only a fresh session helps.
 */

export type StallReason = 'connection_failed' | 'no_media' | 'decoder_stalled';

export type MediaSample = {
  at: number;
  bytesReceived: number;
  framesDecoded: number;
  connectionState: string;
  trackEnded: boolean;
};

export type StallThresholds = {
  /**
   * Bytes flat for this long with a viewer attached = the media plane stopped.
   *
   * Derived, not guessed. A static screen is NOT a silent stream here: the
   * adapter puts a 5s read deadline on the scrcpy video socket and asks the
   * device for an IDR every time it expires (scrcpy/session.go
   * connectAndRead), so a healthy stream cannot be byte-flat much beyond 5s
   * however still the phone is. 10s is twice that, which leaves room for a
   * slow encoder reset without turning an idle device into a false positive.
   */
  noMediaMs: number;
  /**
   * Bytes arriving but no frame decoded for this long = the reference chain is
   * broken (lost P-frame, no IDR coming). Shorter than noMediaMs because this
   * state is never legitimate.
   */
  decoderStallMs: number;
  /** Budget for the very first decoded frame after the answer is applied. */
  firstFrameMs: number;
};

export const DEFAULT_STALL_THRESHOLDS: StallThresholds = {
  noMediaMs: 10_000,
  decoderStallMs: 3_000,
  firstFrameMs: 12_000
};

/**
 * Compare the newest sample against the last one that showed a decoded frame.
 *
 * `anchor` must be the last sample where framesDecoded increased (or the
 * watcher's first sample while nothing has decoded yet), otherwise the ages
 * below measure the wrong interval.
 */
export function classifyStall(
  anchor: MediaSample,
  latest: MediaSample,
  thresholds: StallThresholds = DEFAULT_STALL_THRESHOLDS
): StallReason | null {
  if (latest.connectionState === 'failed' || latest.trackEnded) {
    return 'connection_failed';
  }
  if (latest.framesDecoded > anchor.framesDecoded) return null;
  const ageMs = latest.at - anchor.at;
  if (latest.bytesReceived > anchor.bytesReceived) {
    return ageMs >= thresholds.decoderStallMs ? 'decoder_stalled' : null;
  }
  const budget =
    anchor.framesDecoded === 0 ? thresholds.firstFrameMs : thresholds.noMediaMs;
  return ageMs >= budget ? 'no_media' : null;
}

/**
 * Escalation delays before each recovery attempt, in order.
 *
 * The first is immediate — one freeze should be fixed in the second the user
 * notices it. Everything after backs off, because an attempt that did not work
 * means the fault is upstream of the browser and hammering it costs a scrcpy
 * session lookup, a go2rtc register and an SDP round trip per try, per device.
 */
export const RECOVERY_DELAYS_MS = [0, 2_000, 5_000, 12_000, 30_000, 30_000];
export const MAX_RECOVERY_ATTEMPTS = RECOVERY_DELAYS_MS.length;

/** How long media must flow cleanly before the attempt counter resets. */
export const RECOVERY_RESET_AFTER_MS = 30_000;

/**
 * Delay before attempt `attempt` (0-based), with +/-20% jitter.
 *
 * Jitter is not cosmetic on a device farm. A dashboard shows many tiles, and a
 * go2rtc restart stalls every one of them within the same second; without
 * jitter they all re-create their session on the same tick.
 */
export function recoveryDelayMs(
  attempt: number,
  random: () => number = Math.random
): number {
  const index = Math.min(Math.max(attempt, 0), RECOVERY_DELAYS_MS.length - 1);
  const base = RECOVERY_DELAYS_MS[index];
  if (base <= 0) return 0;
  const spread = base * 0.2;
  return Math.round(base - spread + random() * spread * 2);
}

/**
 * Cap on recoveries running at the same moment across the whole page.
 *
 * Jitter spreads the start times; this bounds the peak. Each recovery makes the
 * adapter re-run start_session (which waits up to 4s for a first frame), so a
 * 40-tile dashboard recovering in lockstep would queue 40 of those against one
 * local machine.
 *
 * ponytail: module-global counter, not a real queue — a blocked recovery is
 * retried on the caller's next backoff step rather than parked. Swap for a
 * proper semaphore if tiles start starving.
 */
const MAX_CONCURRENT_RECOVERIES = 2;
let activeRecoveries = 0;

export function acquireRecoverySlot(): (() => void) | null {
  if (activeRecoveries >= MAX_CONCURRENT_RECOVERIES) return null;
  activeRecoveries += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    activeRecoveries = Math.max(0, activeRecoveries - 1);
  };
}

/** Test hook: the module-level counter would otherwise leak between cases. */
export function resetRecoverySlotsForTest(): void {
  activeRecoveries = 0;
}

/**
 * Cap on first attaches in flight across the whole page.
 *
 * The recovery cap above only covers rebuilds. A fleet grid that mounts 20
 * tiles used to fire 20 session creates, 20 SDP answers and their retries in
 * the same second — through Cloudflare that came back as 520s, and it starved
 * the `/devices/live` poll sharing the origin. Tiles now queue: a slot is held
 * until the first frame, a failure, or ATTACH_SLOT_HOLD_MS, whichever is first.
 *
 * FIFO, so tiles attach in the order they asked — which is mount order, which
 * is top-to-bottom for the rows actually on screen (off-screen tiles never ask).
 */
const configuredMaxConcurrentAttaches = Number(
  process.env.NEXT_PUBLIC_WEBRTC_MAX_CONCURRENT_ATTACHES ?? 4
);
export const MAX_CONCURRENT_ATTACHES = Number.isFinite(
  configuredMaxConcurrentAttaches
)
  ? Math.max(1, Math.min(20, Math.round(configuredMaxConcurrentAttaches)))
  : 4;
/** Long enough for a healthy attach (adapter waits up to 4s for a frame). */
export const ATTACH_SLOT_HOLD_MS = 5_000;

let activeAttaches = 0;
const attachWaiters: Array<() => void> = [];

function grantAttachSlot(): () => void {
  activeAttaches += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    activeAttaches = Math.max(0, activeAttaches - 1);
    attachWaiters.shift()?.();
  };
}

/**
 * Resolve with a release function once a slot is free. Rejects on abort, and an
 * aborted waiter gives up its place in the queue.
 */
export function waitForAttachSlot(signal?: AbortSignal): Promise<() => void> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException('Aborted', 'AbortError'));
  }
  if (activeAttaches < MAX_CONCURRENT_ATTACHES && attachWaiters.length === 0) {
    return Promise.resolve(grantAttachSlot());
  }
  return new Promise((resolve, reject) => {
    const waiter = () => {
      signal?.removeEventListener('abort', onAbort);
      resolve(grantAttachSlot());
    };
    const onAbort = () => {
      const index = attachWaiters.indexOf(waiter);
      if (index >= 0) attachWaiters.splice(index, 1);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    attachWaiters.push(waiter);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

/** Test hook: the module-level queue would otherwise leak between cases. */
export function resetAttachSlotsForTest(): void {
  activeAttaches = 0;
  attachWaiters.length = 0;
}

/** Read one inbound-rtp video sample. Returns null when there is no video yet. */
export async function readMediaSample(
  pc: RTCPeerConnection,
  now: number = Date.now()
): Promise<MediaSample | null> {
  const receiver = pc
    .getReceivers()
    .find((candidate) => candidate.track?.kind === 'video');
  let report: RTCStatsReport;
  try {
    report = await pc.getStats();
  } catch {
    return null;
  }
  let bytesReceived = 0;
  let framesDecoded = 0;
  let found = false;
  report.forEach((entry) => {
    const stat = entry as {
      type?: string;
      kind?: string;
      mediaType?: string;
      bytesReceived?: number;
      framesDecoded?: number;
    };
    if (stat.type !== 'inbound-rtp') return;
    if ((stat.kind ?? stat.mediaType) !== 'video') return;
    found = true;
    bytesReceived += stat.bytesReceived ?? 0;
    framesDecoded += stat.framesDecoded ?? 0;
  });
  if (!found) return null;
  return {
    at: now,
    bytesReceived,
    framesDecoded,
    connectionState: pc.connectionState,
    trackEnded: receiver?.track?.readyState === 'ended'
  };
}

export type MediaProgressWatcherHandle = {
  stop: () => void;
  /**
   * Re-arm after a stall was reported, for a caller that repaired the stream
   * without replacing the connection.
   *
   * The keyframe rung of the recovery ladder is exactly that: it asks the device
   * for an IDR and keeps the PeerConnection. Without this the watcher stays
   * stopped, so a keyframe that did not help would never be noticed and the
   * ladder would never escalate. The anchor is dropped so the next sample starts
   * a fresh window rather than measuring back across the stall.
   */
  resume: () => void;
};

export type MediaProgressWatcherOptions = {
  sample: () => Promise<MediaSample | null>;
  /** Fired once, then the watcher stops until `resume()`. Caller owns recovery. */
  onStall: (reason: StallReason) => void;
  /** Called on every sample that shows a decoded frame. */
  onProgress?: (sample: MediaSample) => void;
  intervalMs?: number;
  thresholds?: StallThresholds;
  isVisible?: () => boolean;
};

/**
 * Poll media progress and report the first confirmed stall.
 *
 * A stall must survive two consecutive samples before it is reported. One tick
 * is not evidence: getStats can return a snapshot taken mid-frame, and a single
 * flat reading on a 1s tick is well within normal scheduling noise.
 */
export function startMediaProgressWatcher({
  sample,
  onStall,
  onProgress,
  intervalMs = 1_000,
  thresholds = DEFAULT_STALL_THRESHOLDS,
  isVisible = defaultIsVisible
}: MediaProgressWatcherOptions): MediaProgressWatcherHandle {
  let anchor: MediaSample | null = null;
  let suspected: StallReason | null = null;
  let closed = false;
  // Set when a stall has been reported and the caller has not said what it did
  // about it yet. Reporting the same stall on every subsequent tick would turn
  // one freeze into a stream of recovery attempts.
  let paused = false;

  const tick = async () => {
    if (closed || paused) return;
    // A hidden tab throttles timers and can pause decoding outright, so every
    // counter goes flat for reasons that have nothing to do with the stream.
    // Drop the anchor so the first sample after the tab returns re-arms rather
    // than reporting the whole hidden period as a stall.
    if (!isVisible()) {
      anchor = null;
      suspected = null;
      return;
    }
    const latest = await sample();
    if (closed || paused || !latest) return;
    if (!anchor) {
      anchor = latest;
      suspected = null;
      return;
    }
    const reason = classifyStall(anchor, latest, thresholds);
    if (!reason) {
      if (latest.framesDecoded > anchor.framesDecoded) {
        anchor = latest;
        onProgress?.(latest);
      }
      suspected = null;
      return;
    }
    if (reason === 'connection_failed' || suspected === reason) {
      paused = true;
      onStall(reason);
      return;
    }
    suspected = reason;
  };

  const timer = setInterval(() => {
    void tick();
  }, intervalMs);
  return {
    stop: () => {
      closed = true;
      clearInterval(timer);
    },
    resume: () => {
      if (closed) return;
      anchor = null;
      suspected = null;
      paused = false;
    }
  };
}

function defaultIsVisible(): boolean {
  if (typeof document === 'undefined') return true;
  return document.visibilityState === 'visible';
}
