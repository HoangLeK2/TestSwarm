import { farmApi } from '@/lib/farm-api';
import {
  DEFAULT_STALL_THRESHOLDS,
  readMediaSample,
  startMediaProgressWatcher,
  type MediaProgressWatcherHandle,
  type MediaSample,
  type StallReason
} from './webrtc-stall';

const configuredIceGatherTimeout = Number(
  process.env.NEXT_PUBLIC_WEBRTC_ICE_GATHER_TIMEOUT_MS ?? 180
);
const WEBRTC_ICE_GATHER_TIMEOUT_MS = Number.isFinite(configuredIceGatherTimeout)
  ? Math.max(0, configuredIceGatherTimeout)
  : 180;
// Milliseconds of receiver-side smoothing. Interactive control is the priority
// here, so this favours latency over hiding jitter; raise it if a lossy link
// makes playback choppy.
const WEBRTC_JITTER_BUFFER_TARGET_MS = Number(
  process.env.NEXT_PUBLIC_WEBRTC_JITTER_BUFFER_MS ?? 40
);
const WEBRTC_SESSION_RETRY_DELAYS_MS = [120, 240, 400, 700, 1000, 1500];
const WEBRTC_ANSWER_RETRY_DELAYS_MS = [80, 160, 240, 360, 520];
const WEBRTC_TRANSIENT_SESSION_STATUSES = new Set([409, 425, 502, 503, 504]);
const WEBRTC_TRANSIENT_ANSWER_STATUSES = new Set([409, 425, 502, 503, 504]);
const configuredSessionTtlSeconds = Number(
  process.env.NEXT_PUBLIC_WEBRTC_SESSION_TTL_SECONDS ?? 300
);
const WEBRTC_SESSION_TTL_SECONDS = Number.isFinite(configuredSessionTtlSeconds)
  ? Math.max(60, Math.min(1800, Math.round(configuredSessionTtlSeconds)))
  : 300;
const configuredSessionHeartbeatMs = Number(
  process.env.NEXT_PUBLIC_WEBRTC_SESSION_HEARTBEAT_MS ??
    Math.min(60_000, Math.floor((WEBRTC_SESSION_TTL_SECONDS * 1000) / 3))
);
const WEBRTC_SESSION_HEARTBEAT_MS = Number.isFinite(
  configuredSessionHeartbeatMs
)
  ? Math.max(
      10_000,
      Math.min(120_000, Math.round(configuredSessionHeartbeatMs))
    )
  : 60_000;

type MediaSession = {
  id: string;
  serial: string;
  viewer_id: string;
  stream_name: string;
  expires_at: string;
};

type SessionDescription = {
  type: 'offer' | 'answer';
  sdp: string;
};

type StartWebRtcStreamOptions = {
  serial: string;
  viewerId: string;
  video: HTMLVideoElement;
  signal?: AbortSignal;
  control?: boolean;
  profile?: 'visible' | 'focused' | 'degraded';
  maxFps?: number;
  maxWidth?: number;
  bitrate?: number;
  onFrame?: () => void;
  onSize?: (width: number, height: number) => void;
  onStall?: (reason: StallReason) => void;
  onProgress?: (sample: MediaSample) => void;
};

type VideoElementWithFrameCallback = HTMLVideoElement & {
  requestVideoFrameCallback?: (
    callback: (now: DOMHighResTimeStamp, metadata: unknown) => void
  ) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

export type WebRtcStreamController = {
  sessionId: string;
  peerConnection: RTCPeerConnection;
  /**
   * Re-point the stall watchdog at whoever currently owns this connection.
   *
   * A controller outlives the hook instance that created it (see the warm
   * controller cache in use-webrtc-video.ts), so the handler captured at
   * creation time can belong to an unmounted component. Without this a reused
   * connection would freeze with nobody listening — the exact state that used
   * to need a page refresh.
   */
  setStallHandler: (handler: ((reason: StallReason) => void) | null) => void;
  /** Re-arm the watchdog after an in-place decoder repair. */
  resumeWatcher: () => void;
  /** Monotonic count of watchdog samples that decoded at least one new frame. */
  getProgressVersion: () => number;
  /** Ask for one adapter-gated IDR tied to this controller's lifecycle. */
  requestKeyframe: () => Promise<void>;
  close: () => Promise<void>;
};

function parseIceServers(): RTCIceServer[] {
  const raw = (
    process.env.NEXT_PUBLIC_WEBRTC_ICE_URLS ?? 'stun:stun.l.google.com:19302'
  ).trim();
  if (!raw) return [];
  const urls = raw
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  if (urls.length === 0) return [];
  const username = process.env.NEXT_PUBLIC_WEBRTC_ICE_USERNAME ?? '';
  const credential = process.env.NEXT_PUBLIC_WEBRTC_ICE_CREDENTIAL ?? '';
  return username || credential ? [{ urls, username, credential }] : [{ urls }];
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await farmApi.post<T>(path, body);
  return response.data;
}

async function deleteJson(path: string): Promise<void> {
  await farmApi.delete(path);
}

async function keepWebRtcSessionAlive(
  sessionId: string,
  signal?: AbortSignal
): Promise<void> {
  if (signal?.aborted) return;
  await postJson(`/media/webrtc/sessions/${sessionId}/heartbeat`, {
    ttl_seconds: WEBRTC_SESSION_TTL_SECONDS
  });
}

/** Ask the adapter for one rate-limited IDR without replacing this session. */
export async function requestWebRtcKeyframe(
  sessionId: string,
  signal?: AbortSignal
): Promise<void> {
  await farmApi.post(
    `/media/webrtc/sessions/${sessionId}/keyframe`,
    {},
    { timeout: 3_000, signal }
  );
}

/**
 * Shrink the receiver's jitter buffer.
 *
 * The default buffer is tuned for passive video, where a few hundred ms of
 * smoothing costs nothing. Here the same buffer sits between a tap and the
 * screen reacting to it, so it is felt directly. Both properties are recent
 * and vendor-specific, hence the guarded assignment: where they are missing
 * the browser keeps its adaptive default rather than breaking playback.
 */
function minimiseReceiverBuffering(receiver: RTCRtpReceiver | undefined): void {
  if (!receiver) return;
  const target = receiver as RTCRtpReceiver & {
    jitterBufferTarget?: number | null;
    playoutDelayHint?: number | null;
  };
  try {
    if ('jitterBufferTarget' in target) {
      target.jitterBufferTarget = WEBRTC_JITTER_BUFFER_TARGET_MS;
    }
    if ('playoutDelayHint' in target) {
      target.playoutDelayHint = WEBRTC_JITTER_BUFFER_TARGET_MS / 1000;
    }
  } catch {
    // Read-only in some engines; the adaptive default still works.
  }
}

function httpStatus(error: unknown): number | null {
  if (!error || typeof error !== 'object' || !('response' in error)) {
    return null;
  }
  const response = (error as { response?: { status?: unknown } }).response;
  return typeof response?.status === 'number' ? response.status : null;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted)
    return Promise.reject(new DOMException('Aborted', 'AbortError'));
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(done, ms);
    function done() {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }
    function onAbort() {
      window.clearTimeout(timeout);
      signal?.removeEventListener('abort', onAbort);
      reject(new DOMException('Aborted', 'AbortError'));
    }
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

async function postWebRtcAnswerWithRetry(
  sessionId: string,
  offer: SessionDescription,
  signal?: AbortSignal
): Promise<SessionDescription> {
  let lastError: unknown;
  for (
    let attempt = 0;
    attempt <= WEBRTC_ANSWER_RETRY_DELAYS_MS.length;
    attempt += 1
  ) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    try {
      return await postJson<SessionDescription>(
        `/media/webrtc/sessions/${sessionId}/answer`,
        offer
      );
    } catch (error) {
      lastError = error;
      const status = httpStatus(error);
      if (
        attempt >= WEBRTC_ANSWER_RETRY_DELAYS_MS.length ||
        status === null ||
        !WEBRTC_TRANSIENT_ANSWER_STATUSES.has(status)
      ) {
        throw error;
      }
      await sleep(WEBRTC_ANSWER_RETRY_DELAYS_MS[attempt], signal);
    }
  }
  throw lastError;
}

async function postWebRtcSessionWithRetry(
  payload: Record<string, unknown>,
  signal?: AbortSignal
): Promise<MediaSession> {
  let lastError: unknown;
  for (
    let attempt = 0;
    attempt <= WEBRTC_SESSION_RETRY_DELAYS_MS.length;
    attempt += 1
  ) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    try {
      return await postJson<MediaSession>('/media/webrtc/sessions', payload);
    } catch (error) {
      lastError = error;
      const status = httpStatus(error);
      if (
        attempt >= WEBRTC_SESSION_RETRY_DELAYS_MS.length ||
        status === null ||
        !WEBRTC_TRANSIENT_SESSION_STATUSES.has(status)
      ) {
        throw error;
      }
      await sleep(WEBRTC_SESSION_RETRY_DELAYS_MS[attempt], signal);
    }
  }
  throw lastError;
}

async function waitForIceGatheringComplete(
  pc: RTCPeerConnection,
  timeoutMs = WEBRTC_ICE_GATHER_TIMEOUT_MS
): Promise<void> {
  if (pc.iceGatheringState === 'complete') return;
  await new Promise<void>((resolve) => {
    const timeout = window.setTimeout(done, timeoutMs);
    function done() {
      window.clearTimeout(timeout);
      pc.removeEventListener('icegatheringstatechange', onChange);
      resolve();
    }
    function onChange() {
      if (pc.iceGatheringState === 'complete') done();
    }
    pc.addEventListener('icegatheringstatechange', onChange);
  });
}

export async function startWebRtcStream({
  serial,
  viewerId,
  video,
  signal,
  control,
  profile,
  maxFps,
  maxWidth,
  bitrate,
  onFrame,
  onSize,
  onStall,
  onProgress
}: StartWebRtcStreamOptions): Promise<WebRtcStreamController> {
  const payload: Record<string, unknown> = {
    org_id: 'local-org',
    user_id: 'local-user',
    serial,
    viewer_id: viewerId,
    ttl_seconds: WEBRTC_SESSION_TTL_SECONDS
  };
  if (control !== undefined) payload.control = control;
  if (profile !== undefined) payload.profile = profile;
  if (maxFps !== undefined) payload.max_fps = maxFps;
  if (maxWidth !== undefined) payload.max_width = maxWidth;
  if (bitrate !== undefined) payload.bitrate = bitrate;
  const session = await postWebRtcSessionWithRetry(payload, signal);
  let sessionOpen = true;
  let heartbeatTimer: number | null = window.setInterval(() => {
    keepWebRtcSessionAlive(session.id, signal).catch(() => {});
  }, WEBRTC_SESSION_HEARTBEAT_MS);
  const closeSession = async () => {
    if (!sessionOpen) return;
    sessionOpen = false;
    if (heartbeatTimer !== null) {
      window.clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
    await deleteJson(`/media/webrtc/sessions/${session.id}`).catch(() => {});
  };
  if (signal?.aborted) {
    await closeSession();
    throw new DOMException('Aborted', 'AbortError');
  }

  const pc = new RTCPeerConnection({ iceServers: parseIceServers() });
  pc.addTransceiver('video', { direction: 'recvonly' });

  let stallHandler: ((reason: StallReason) => void) | null = onStall ?? null;
  const setStallHandler = (handler: ((reason: StallReason) => void) | null) => {
    stallHandler = handler;
  };
  let watcher: MediaProgressWatcherHandle | null = null;
  let progressVersion = 0;

  let firstFrameSeen = false;
  let frameCallbackHandle: number | null = null;
  const markFrame = () => {
    firstFrameSeen = true;
    onFrame?.();
    if (video.videoWidth && video.videoHeight) {
      onSize?.(video.videoWidth, video.videoHeight);
    }
  };
  const cancelFrameCallback = () => {
    if (frameCallbackHandle === null) return;
    const typedVideo = video as VideoElementWithFrameCallback;
    typedVideo.cancelVideoFrameCallback?.(frameCallbackHandle);
    frameCallbackHandle = null;
  };
  const requestFirstVideoFrame = () => {
    if (firstFrameSeen) return;
    const typedVideo = video as VideoElementWithFrameCallback;
    if (typedVideo.requestVideoFrameCallback) {
      cancelFrameCallback();
      frameCallbackHandle = typedVideo.requestVideoFrameCallback(() => {
        frameCallbackHandle = null;
        markFrame();
      });
      return;
    }
    if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      markFrame();
    }
  };
  video.addEventListener('loadeddata', markFrame);
  video.addEventListener('canplay', requestFirstVideoFrame);
  video.addEventListener('playing', requestFirstVideoFrame);
  video.addEventListener('resize', markFrame);

  pc.ontrack = (event) => {
    const stream = event.streams[0] ?? new MediaStream([event.track]);
    if (video.srcObject !== stream) {
      video.srcObject = stream;
    }
    minimiseReceiverBuffering(event.receiver);
    video.play().catch(() => {});
    requestFirstVideoFrame();
  };

  try {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await waitForIceGatheringComplete(pc);

    const local = pc.localDescription;
    if (!local?.sdp) {
      throw new Error('WebRTC offer SDP is empty');
    }
    const answer = await postWebRtcAnswerWithRetry(
      session.id,
      { type: local.type as 'offer', sdp: local.sdp },
      signal
    );
    await pc.setRemoteDescription(answer);
    // Only arm the watchdog once media is supposed to be flowing. Before this
    // point a flat counter means "still negotiating", which the 425 retry
    // ladder above already owns.
    watcher = startMediaProgressWatcher({
      sample: () => readMediaSample(pc),
      thresholds: DEFAULT_STALL_THRESHOLDS,
      onProgress: (latest) => {
        progressVersion += 1;
        onProgress?.(latest);
      },
      onStall: (reason) => stallHandler?.(reason)
    });
  } catch (error) {
    watcher?.stop();
    watcher = null;
    cancelFrameCallback();
    video.removeEventListener('loadeddata', markFrame);
    video.removeEventListener('canplay', requestFirstVideoFrame);
    video.removeEventListener('playing', requestFirstVideoFrame);
    video.removeEventListener('resize', markFrame);
    pc.close();
    video.srcObject = null;
    await closeSession();
    throw error;
  }

  const close = async () => {
    watcher?.stop();
    watcher = null;
    stallHandler = null;
    cancelFrameCallback();
    video.removeEventListener('loadeddata', markFrame);
    video.removeEventListener('canplay', requestFirstVideoFrame);
    video.removeEventListener('playing', requestFirstVideoFrame);
    video.removeEventListener('resize', markFrame);
    pc.close();
    // Keep the ended MediaStream attached until the replacement connection's
    // ontrack swaps it. Chromium retains the last painted frame this way;
    // clearing srcObject here caused every recovery to flash a black screen.
    // An unmounted video is collected normally, and disabling WebRTC hides it.
    await closeSession();
  };

  signal?.addEventListener('abort', () => {
    close().catch(() => {});
  });

  return {
    sessionId: session.id,
    peerConnection: pc,
    setStallHandler,
    resumeWatcher: () => watcher?.resume(),
    getProgressVersion: () => progressVersion,
    requestKeyframe: () => requestWebRtcKeyframe(session.id, signal),
    close
  };
}
