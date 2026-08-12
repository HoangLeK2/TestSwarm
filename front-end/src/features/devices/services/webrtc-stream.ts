import { farmApi } from '@/lib/farm-api';

const configuredIceGatherTimeout = Number(
  process.env.NEXT_PUBLIC_WEBRTC_ICE_GATHER_TIMEOUT_MS ?? 180
);
const WEBRTC_ICE_GATHER_TIMEOUT_MS = Number.isFinite(configuredIceGatherTimeout)
  ? Math.max(0, configuredIceGatherTimeout)
  : 180;
const WEBRTC_ANSWER_RETRY_DELAYS_MS = [80, 160, 240, 360, 520];
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
  onSize
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
  const session = await postJson<MediaSession>(
    '/media/webrtc/sessions',
    payload
  );
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
  } catch (error) {
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
    cancelFrameCallback();
    video.removeEventListener('loadeddata', markFrame);
    video.removeEventListener('canplay', requestFirstVideoFrame);
    video.removeEventListener('playing', requestFirstVideoFrame);
    video.removeEventListener('resize', markFrame);
    pc.close();
    video.srcObject = null;
    await closeSession();
  };

  signal?.addEventListener('abort', () => {
    close().catch(() => {});
  });

  return { sessionId: session.id, peerConnection: pc, close };
}
