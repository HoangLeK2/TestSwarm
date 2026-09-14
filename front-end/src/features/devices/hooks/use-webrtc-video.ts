import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject
} from 'react';
import {
  requestWebRtcKeyframe,
  startWebRtcStream,
  type WebRtcStreamController
} from '../services/webrtc-stream';
import {
  MAX_RECOVERY_ATTEMPTS,
  RECOVERY_RESET_AFTER_MS,
  acquireRecoverySlot,
  recoveryDelayMs,
  type StallReason
} from '../services/webrtc-stall';

type UseWebRtcVideoOptions = {
  enabled: boolean;
  restartKey?: number;
  control?: boolean;
  profile?: 'visible' | 'focused' | 'degraded';
  maxFps?: number;
  maxWidth?: number;
  bitrate?: number;
  onFrame?: () => void;
  onSize?: (width: number, height: number) => void;
  onError?: (error: unknown) => void;
};

const configuredCloseGraceMs = Number(
  process.env.NEXT_PUBLIC_WEBRTC_TRANSIENT_CLOSE_GRACE_MS ?? 8000
);
const WEBRTC_TRANSIENT_CLOSE_GRACE_MS = Number.isFinite(configuredCloseGraceMs)
  ? Math.max(0, Math.min(15_000, Math.round(configuredCloseGraceMs)))
  : 8000;

type WarmWebRtcEntry = {
  controller: WebRtcStreamController;
  refs: number;
  closeTimer: number | null;
};

const warmWebRtcControllers = new Map<string, WarmWebRtcEntry>();

export function useWebRtcVideo(
  serial: string,
  videoRef: RefObject<HTMLVideoElement | null>,
  {
    enabled,
    restartKey = 0,
    control,
    profile,
    maxFps,
    maxWidth,
    bitrate,
    onFrame,
    onSize,
    onError
  }: UseWebRtcVideoOptions
) {
  const viewerId = useMemo(
    () => `webrtc-${Math.random().toString(36).slice(2)}-${Date.now()}`,
    []
  );
  const controllerRef = useRef<WebRtcStreamController | null>(null);
  const [active, setActive] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [failed, setFailed] = useState(false);
  const [stalled, setStalled] = useState(false);
  // Bumped by the stall recovery ladder, on the rung above the keyframe request.
  // Part of streamKey so a bump rebuilds the session and the PeerConnection:
  // that replaces a connection which may itself be the broken part, and creating
  // a session also makes the adapter burst IDRs at the phone (controlplane
  // startSession). It does not restart scrcpy — Manager.Start reuses a session
  // whose profile already matches.
  const [recoveryEpoch, setRecoveryEpoch] = useState(0);
  const recoveryAttemptRef = useRef(0);
  const recoveryTimerRef = useRef<number | null>(null);
  const recoveryInFlightRef = useRef(false);
  const recoverySlotRef = useRef<(() => void) | null>(null);
  const healthySinceRef = useRef(0);
  // One keyframe per ladder cycle. It is the cheap rung — no black flash, no new
  // session — but a stall it does not fix is a stall a second one will not fix
  // either, and repeating it would stop the ladder ever reaching the rung that
  // does work.
  const keyframeUsedRef = useRef(false);
  const streamKey = useMemo(
    () =>
      [
        serial,
        control ? 'control' : 'view',
        profile ?? '',
        maxFps ?? '',
        maxWidth ?? '',
        bitrate ?? '',
        restartKey,
        recoveryEpoch
      ].join('|'),
    [
      bitrate,
      control,
      maxFps,
      maxWidth,
      profile,
      recoveryEpoch,
      restartKey,
      serial
    ]
  );
  const streamKeyRef = useRef(streamKey);
  streamKeyRef.current = streamKey;

  const releaseRecoverySlot = useCallback(() => {
    recoverySlotRef.current?.();
    recoverySlotRef.current = null;
    recoveryInFlightRef.current = false;
  }, []);

  const handleProgress = useCallback(() => {
    setStalled(false);
    const now = Date.now();
    if (healthySinceRef.current === 0) {
      healthySinceRef.current = now;
      return;
    }
    // Only forgive the ladder after the stream has genuinely settled. Resetting
    // on the first frame after a recovery would let a stream that freezes every
    // few seconds retry at zero backoff forever.
    if (now - healthySinceRef.current >= RECOVERY_RESET_AFTER_MS) {
      recoveryAttemptRef.current = 0;
      keyframeUsedRef.current = false;
      setFailed(false);
    }
  }, []);

  const scheduleRecovery = useCallback((reason: StallReason) => {
    if (recoveryTimerRef.current !== null) return;
    const attempt = recoveryAttemptRef.current;
    if (attempt >= MAX_RECOVERY_ATTEMPTS) {
      // Out of rungs. Surface it rather than retrying forever: at this point
      // the fault is upstream of the browser and only an operator can see it.
      setFailed(true);
      return;
    }
    recoveryTimerRef.current = window.setTimeout(() => {
      recoveryTimerRef.current = null;
      const release = acquireRecoverySlot();
      if (!release) {
        // The page-wide cap is full. Count the attempt so the next wait is
        // longer, and come back on that schedule.
        recoveryAttemptRef.current += 1;
        scheduleRecovery(reason);
        return;
      }
      recoverySlotRef.current = release;
      recoveryInFlightRef.current = true;
      recoveryAttemptRef.current += 1;
      healthySinceRef.current = 0;
      // Drop the frozen connection now. Leaving it to the warm-cache grace
      // timer would let the very next mount hand the user the dead one back.
      evictWarmController(streamKeyRef.current);
      setRecoveryEpoch((value) => value + 1);
    }, recoveryDelayMs(attempt));
  }, []);

  const handleStall = useCallback(
    (reason: StallReason) => {
      if (recoveryInFlightRef.current) return;
      setStalled(true);
      healthySinceRef.current = 0;
      const controller = controllerRef.current;
      // `decoder_stalled` means bytes are arriving and nothing decodes: the
      // reference chain is broken and a single IDR repairs it, keeping the
      // connection and costing ~100ms against ~1s and a black flash for a
      // rebuild. The other reasons mean no media at all, where a keyframe has
      // nothing to travel over.
      if (
        reason === 'decoder_stalled' &&
        !keyframeUsedRef.current &&
        controller
      ) {
        keyframeUsedRef.current = true;
        requestWebRtcKeyframe(controller.sessionId)
          .then(() => {
            // Re-arm rather than declaring victory. If the keyframe did not
            // arrive the watcher reports the same stall a few seconds later and
            // this branch is already spent, so the next report rebuilds. The
            // attempt counter stays untouched, so a keyframe that works costs
            // the ladder nothing.
            controller.resumeWatcher();
          })
          .catch(() => {
            // Includes the timeout from an adapter built before this endpoint
            // existed. Not an error, just a rung that is not there.
            scheduleRecovery(reason);
          });
        return;
      }
      scheduleRecovery(reason);
    },
    [scheduleRecovery]
  );

  useEffect(
    () => () => {
      if (recoveryTimerRef.current !== null) {
        window.clearTimeout(recoveryTimerRef.current);
        recoveryTimerRef.current = null;
      }
      recoverySlotRef.current?.();
      recoverySlotRef.current = null;
    },
    []
  );

  useEffect(() => {
    if (!enabled || !serial || !videoRef.current) {
      setActive(false);
      setConnecting(false);
      return;
    }

    const video = videoRef.current;
    const reused = acquireWarmController(streamKey);
    if (reused) {
      controllerRef.current = reused.controller;
      // The watchdog inside the controller still points at the hook instance
      // that created it, which may be long unmounted. Take it over.
      reused.controller.setStallHandler(handleStall);
      const detach = attachExistingController(
        reused.controller,
        video,
        () => {
          setActive(true);
          setConnecting(false);
          onFrame?.();
        },
        onSize
      );
      setFailed(false);
      setStalled(false);
      setConnecting(false);
      setActive(true);
      return () => {
        detach();
        reused.controller.setStallHandler(null);
        releaseWarmController(streamKey);
        controllerRef.current = null;
        setActive(false);
        setConnecting(false);
      };
    }

    const abort = new AbortController();
    setConnecting(true);
    setFailed(false);
    startWebRtcStream({
      serial,
      viewerId,
      video,
      signal: abort.signal,
      control,
      profile,
      maxFps,
      maxWidth,
      bitrate,
      onFrame: () => {
        setActive(true);
        setConnecting(false);
        onFrame?.();
      },
      onSize,
      onStall: handleStall,
      onProgress: handleProgress
    })
      .then((controller) => {
        releaseRecoverySlot();
        if (abort.signal.aborted) {
          controller.close().catch(() => {});
          return;
        }
        controllerRef.current = controller;
        warmWebRtcControllers.set(streamKey, {
          controller,
          refs: 1,
          closeTimer: null
        });
      })
      .catch((error) => {
        releaseRecoverySlot();
        if (abort.signal.aborted) return;
        setActive(false);
        setConnecting(false);
        setFailed(true);
        onError?.(error);
        // A rebuild that cannot even get a session is still a stall from the
        // user's side, so it stays on the same ladder instead of dead-ending.
        scheduleRecovery('connection_failed');
      });

    return () => {
      abort.abort();
      const controller = controllerRef.current;
      controllerRef.current = null;
      if (controller) {
        releaseWarmController(streamKey);
      }
      setActive(false);
      setConnecting(false);
    };
  }, [
    bitrate,
    control,
    enabled,
    handleProgress,
    handleStall,
    maxFps,
    maxWidth,
    onError,
    onFrame,
    onSize,
    profile,
    releaseRecoverySlot,
    restartKey,
    scheduleRecovery,
    serial,
    streamKey,
    videoRef,
    viewerId
  ]);

  return { active, connecting, failed, stalled };
}

/** Drop a cached controller immediately instead of on the grace timer. */
function evictWarmController(key: string) {
  const entry = warmWebRtcControllers.get(key);
  if (!entry) return;
  warmWebRtcControllers.delete(key);
  if (entry.closeTimer !== null) {
    window.clearTimeout(entry.closeTimer);
    entry.closeTimer = null;
  }
  entry.controller.setStallHandler(null);
  entry.controller.close().catch(() => {});
}

function acquireWarmController(key: string): WarmWebRtcEntry | null {
  const entry = warmWebRtcControllers.get(key);
  if (!entry) return null;
  // Anything past `connected`/`connecting` is a connection that will never
  // carry media again. Checking only for `closed` — as this did — handed back
  // `failed` and `disconnected` connections, so a remount reattached the frozen
  // picture and the user's only remaining move was a page refresh.
  const state = entry.controller.peerConnection.connectionState;
  if (state !== 'new' && state !== 'connecting' && state !== 'connected') {
    warmWebRtcControllers.delete(key);
    if (entry.closeTimer !== null) {
      window.clearTimeout(entry.closeTimer);
      entry.closeTimer = null;
    }
    entry.controller.close().catch(() => {});
    return null;
  }
  if (entry.closeTimer !== null) {
    window.clearTimeout(entry.closeTimer);
    entry.closeTimer = null;
  }
  entry.refs += 1;
  return entry;
}

function releaseWarmController(key: string) {
  const entry = warmWebRtcControllers.get(key);
  if (!entry) return;
  entry.refs = Math.max(0, entry.refs - 1);
  if (entry.refs > 0 || entry.closeTimer !== null) return;
  entry.closeTimer = window.setTimeout(() => {
    const current = warmWebRtcControllers.get(key);
    if (!current || current.refs > 0) return;
    warmWebRtcControllers.delete(key);
    current.controller.close().catch(() => {});
  }, WEBRTC_TRANSIENT_CLOSE_GRACE_MS);
}

function attachExistingController(
  controller: WebRtcStreamController,
  video: HTMLVideoElement,
  onFrame: () => void,
  onSize?: (width: number, height: number) => void
) {
  const track = controller.peerConnection
    .getReceivers()
    .map((receiver) => receiver.track)
    .find((candidate) => candidate?.kind === 'video');
  if (track && video.srcObject === null) {
    video.srcObject = new MediaStream([track]);
  }
  const markFrame = () => {
    onFrame();
    if (video.videoWidth && video.videoHeight) {
      onSize?.(video.videoWidth, video.videoHeight);
    }
  };
  video.addEventListener('loadeddata', markFrame);
  video.addEventListener('resize', markFrame);
  video.play().catch(() => {});
  if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
    markFrame();
  }
  return () => {
    video.removeEventListener('loadeddata', markFrame);
    video.removeEventListener('resize', markFrame);
    if (video.srcObject instanceof MediaStream) {
      video.srcObject = null;
    }
  };
}
