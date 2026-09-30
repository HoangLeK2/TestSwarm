import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject
} from 'react';
import {
  startWebRtcStream,
  type WebRtcStreamController
} from '../services/webrtc-stream';
import {
  ATTACH_SLOT_HOLD_MS,
  MAX_RECOVERY_ATTEMPTS,
  RECOVERY_RESET_AFTER_MS,
  acquireKeyframeRepair,
  acquireRecoverySlot,
  recoveryDelayMs,
  shouldRequestWebRtcRefreshAfterInput,
  type WebRtcAttachPriority,
  waitForAttachSlot,
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
const WEBRTC_INPUT_REFRESH_WAIT_MS = 1_200;
// Waiting for the page-wide recovery semaphore is not a failed media repair.
// Retry the slot quickly without consuming one of the bounded recovery rungs.
const WEBRTC_RECOVERY_SLOT_RETRY_MS = 500;

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
  // The ladder ran out. Distinct from `failed`, which is also true between
  // rungs while a retry is still coming.
  const [gaveUp, setGaveUp] = useState(false);
  // Part of streamKey so a bump rebuilds the session and PeerConnection without
  // restarting scrcpy; Manager.Start reuses a matching device stream.
  const [recoveryEpoch, setRecoveryEpoch] = useState(0);
  const recoveryAttemptRef = useRef(0);
  const recoveryTimerRef = useRef<number | null>(null);
  const inputRefreshTimerRef = useRef<number | null>(null);
  const lastInputKeyframeRef = useRef<{
    controller: WebRtcStreamController;
    progressVersion: number;
  } | null>(null);
  const recoveryInFlightRef = useRef(false);
  const recoverySlotRef = useRef<(() => void) | null>(null);
  const healthySinceRef = useRef(0);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const previousSerialRef = useRef(serial);
  // One in-place decoder repair per recovery cycle. Repeating IDR resets can
  // reconfigure fragile phone encoders, so a failed repair escalates instead.
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
  // Fleet previews may queue behind each other, but an explicitly opened
  // control/detail stream must take the next free attach slot.
  const attachPriority: WebRtcAttachPriority =
    profile === 'visible' || profile === 'degraded' ? 'preview' : 'interactive';

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
      setGaveUp(false);
    }
  }, []);

  const scheduleRecovery = useCallback((reason: StallReason) => {
    if (!enabledRef.current || recoveryTimerRef.current !== null) return;
    const attempt = recoveryAttemptRef.current;
    if (attempt >= MAX_RECOVERY_ATTEMPTS) {
      // Out of rungs. Surface it rather than retrying forever: at this point
      // the fault is upstream of the browser and only an operator can see it.
      setFailed(true);
      setGaveUp(true);
      return;
    }
    const attemptRecovery = () => {
      recoveryTimerRef.current = null;
      if (!enabledRef.current) return;
      const release = acquireRecoverySlot();
      if (!release) {
        // The page-wide cap is full. Capacity contention is not a failed
        // recovery, so keep this rung and wait instead of eventually giving up
        // without ever repairing the media session.
        recoveryTimerRef.current = window.setTimeout(() => {
          attemptRecovery();
        }, WEBRTC_RECOVERY_SLOT_RETRY_MS);
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
    };
    recoveryTimerRef.current = window.setTimeout(
      attemptRecovery,
      recoveryDelayMs(attempt)
    );
  }, []);

  const requestFrameRefresh = useCallback(() => {
    const controller = controllerRef.current;
    if (!controller) return;
    // Keep the earliest deadline while the operator is tapping or typing. A
    // debounce would postpone repair forever on an already-frozen screen.
    if (inputRefreshTimerRef.current !== null) return;
    const progressVersionAtInput = controller.getProgressVersion();
    inputRefreshTimerRef.current = window.setTimeout(() => {
      inputRefreshTimerRef.current = null;
      if (controllerRef.current !== controller) return;
      if (
        !shouldRequestWebRtcRefreshAfterInput(
          progressVersionAtInput,
          controller.getProgressVersion()
        )
      ) {
        return;
      }
      const currentProgressVersion = controller.getProgressVersion();
      const lastKeyframe = lastInputKeyframeRef.current;
      if (
        lastKeyframe?.controller === controller &&
        lastKeyframe.progressVersion === currentProgressVersion
      ) {
        return;
      }
      if (!acquireKeyframeRepair(serial)) return;
      controller
        .requestKeyframe()
        .then(() => {
          if (controllerRef.current !== controller) return;
          lastInputKeyframeRef.current = {
            controller,
            progressVersion: currentProgressVersion
          };
        })
        .catch(() => {});
    }, WEBRTC_INPUT_REFRESH_WAIT_MS);
  }, [serial]);

  const handleStall = useCallback(
    (reason: StallReason) => {
      if (recoveryInFlightRef.current) return;
      if (
        healthySinceRef.current > 0 &&
        Date.now() - healthySinceRef.current >= RECOVERY_RESET_AFTER_MS
      ) {
        // A repaired stream can be perfectly healthy while the Android screen
        // is static and emits no further frames. Reset the ladder here too, so
        // the next real stall still gets the cheap keyframe rung.
        recoveryAttemptRef.current = 0;
        keyframeUsedRef.current = false;
        setFailed(false);
        setGaveUp(false);
      }
      setStalled(true);
      healthySinceRef.current = 0;
      const controller = controllerRef.current;
      if (
        reason === 'decoder_stalled' &&
        !keyframeUsedRef.current &&
        controller
      ) {
        keyframeUsedRef.current = true;
        if (!acquireKeyframeRepair(serial)) {
          // Another viewer for this device just requested the same IDR. It is
          // shared at the publisher, so wait for that frame on this connection.
          controller.resumeWatcher();
          return;
        }
        controller
          .requestKeyframe()
          .then(() => {
            if (controllerRef.current !== controller) return;
            // If the IDR does not repair decoding, the re-armed watcher reports
            // again and this spent rung escalates to a session rebuild.
            controller.resumeWatcher();
          })
          .catch(() => {
            if (controllerRef.current !== controller) return;
            scheduleRecovery(reason);
          });
        return;
      }
      scheduleRecovery(reason);
    },
    [scheduleRecovery, serial]
  );

  // A manual restart gets a full ladder, not whatever the last run left over.
  useEffect(() => {
    recoveryAttemptRef.current = 0;
    keyframeUsedRef.current = false;
    setGaveUp(false);
  }, [restartKey, serial]);

  useEffect(
    () => () => {
      if (recoveryTimerRef.current !== null) {
        window.clearTimeout(recoveryTimerRef.current);
        recoveryTimerRef.current = null;
      }
      if (inputRefreshTimerRef.current !== null) {
        window.clearTimeout(inputRefreshTimerRef.current);
        inputRefreshTimerRef.current = null;
      }
      recoverySlotRef.current?.();
      recoverySlotRef.current = null;
    },
    []
  );

  useEffect(() => {
    if (previousSerialRef.current === serial) return;
    previousSerialRef.current = serial;
    if (recoveryTimerRef.current !== null) {
      window.clearTimeout(recoveryTimerRef.current);
      recoveryTimerRef.current = null;
    }
    releaseRecoverySlot();
    lastInputKeyframeRef.current = null;
    const video = videoRef.current;
    if (video?.srcObject instanceof MediaStream) {
      // The last painted frame is safe only for recovery of the same device.
      // Never show one device while controls already target another serial.
      video.srcObject = null;
    }
  }, [releaseRecoverySlot, serial, videoRef]);

  useEffect(() => {
    if (!enabled || !serial || !videoRef.current) {
      if (recoveryTimerRef.current !== null) {
        window.clearTimeout(recoveryTimerRef.current);
        recoveryTimerRef.current = null;
      }
      releaseRecoverySlot();
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
    // Queue behind the page-wide attach cap; the slot goes back on the first
    // frame, on failure, or after ATTACH_SLOT_HOLD_MS so one slow phone cannot
    // hold the rest of the grid hostage.
    let releaseAttachSlot: (() => void) | null = null;
    let attachHoldTimer: number | undefined;
    const freeAttachSlot = () => {
      if (attachHoldTimer !== undefined) {
        window.clearTimeout(attachHoldTimer);
        attachHoldTimer = undefined;
      }
      releaseAttachSlot?.();
      releaseAttachSlot = null;
    };
    setConnecting(true);
    setFailed(false);
    waitForAttachSlot(abort.signal, attachPriority)
      .then((release) => {
        releaseAttachSlot = release;
        attachHoldTimer = window.setTimeout(
          freeAttachSlot,
          ATTACH_SLOT_HOLD_MS
        );
        return startWebRtcStream({
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
            freeAttachSlot();
            setActive(true);
            setConnecting(false);
            onFrame?.();
          },
          onSize,
          onStall: handleStall,
          onProgress: handleProgress
        });
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
        freeAttachSlot();
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
      freeAttachSlot();
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
    attachPriority,
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

  return {
    active,
    connecting,
    failed,
    stalled,
    gaveUp,
    requestFrameRefresh
  };
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
  } else if (track && video.srcObject instanceof MediaStream) {
    const attachedTrack = video.srcObject.getVideoTracks()[0];
    if (attachedTrack !== track) {
      // A recovery keeps the last painted frame until the replacement is
      // ready. Warm reuse must still replace that ended track explicitly.
      video.srcObject = new MediaStream([track]);
    }
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
