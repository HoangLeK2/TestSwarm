'use client';

import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MutableRefObject
} from 'react';
import { useGesture } from '@use-gesture/react';
import type { Device } from '../types';
import { serialToId } from '../helpers';
import { deviceFarmMediaBase, farmApi } from '@/lib/farm-api';
import { Switch } from '@/components/ui/switch';
import { toast } from 'sonner';
import { tokenStorage } from '@/lib/token-storage';
import { useH264Video } from '../hooks/use-h264-canvas';
import { useWebRtcVideo } from '../hooks/use-webrtc-video';
import {
  ensureWatchSerial,
  requestIdr,
  subscribeDeviceFarm
} from '../services/ws';
import { useTranslations } from 'next-intl';
import { usePathname } from 'next/navigation';
import { SHOW_RELAY_SCRCPY_UI_TOGGLE } from '../streaming-ui-flags';
import { Badge } from '@/components/ui/badge';
import { useTabNetworkActive } from '../hooks/use-tab-network-active';
import {
  attachScrcpyStream,
  detachScrcpyStream,
  detachScrcpyStreamOnPageHide,
  isRecoverableScrcpyAttachError,
  isScrcpyAttachCancellation,
  scrcpyAttachErrorMessage,
  type ScrcpyAttachOptions
} from '../services/scrcpy-stream';
import {
  createScrcpyViewerSession,
  type ScrcpyViewerRole
} from '../services/scrcpy-viewer-session';
import {
  H264_INPUT_REFRESH_MIN_INTERVAL_MS,
  H264_INPUT_REFRESH_WAIT_MS,
  shouldRequestH264RefreshAfterInput
} from '../lib/h264-input-refresh';

type Size = { width: number; height: number };
type StreamingFlags = {
  mode: string;
  autoAttach: boolean;
};
const SCRCPY_ATTACH_RETRY_MS = 3_000;
const SCRCPY_ATTACH_DEDUPE_MS = 90_000;
const SCRCPY_TRANSIENT_UNMOUNT_DETACH_DELAY_MS = 5_000;
const H264_PRIMARY_VISIBLE_RECOVERY_MIN_MS = 5_000;
const recentScrcpyAttachByViewer = new Map<string, number>();
const pendingScrcpyDetachByViewer = new Map<
  string,
  ReturnType<typeof setTimeout>
>();
let cachedStreamingFlags: StreamingFlags | null = null;
let pendingStreamingFlags: Promise<StreamingFlags> | null = null;

type ObjectFitRect = {
  left: number;
  top: number;
  width: number;
  height: number;
  scale: number;
};

export type DeviceScreenTransport = 'auto' | 'h264-only' | 'webrtc';

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(value, max));
}

function loadStreamingFlags(): Promise<StreamingFlags> {
  if (cachedStreamingFlags) return Promise.resolve(cachedStreamingFlags);
  if (!pendingStreamingFlags) {
    pendingStreamingFlags = farmApi
      .get<{ streaming_mode?: string; streaming_auto_attach_scrcpy?: boolean }>(
        '/config'
      )
      .then((res) => ({
        mode: String(res.data?.streaming_mode ?? 'periodic'),
        autoAttach: Boolean(res.data?.streaming_auto_attach_scrcpy ?? true)
      }))
      .catch(() => ({ mode: 'periodic', autoAttach: true }))
      .then((flags) => {
        cachedStreamingFlags = flags;
        pendingStreamingFlags = null;
        return flags;
      });
  }
  return pendingStreamingFlags;
}

function scrcpyAttachProfileKey(options?: ScrcpyAttachOptions): string {
  if (!options) return 'default';
  return [
    options.enableControl ?? 'default',
    options.maxFps ?? 'default',
    options.maxWidth ?? 'default',
    options.bitrate ?? 'default'
  ].join(':');
}

function scrcpyAttachKey(
  serial: string,
  viewerId: string,
  options?: ScrcpyAttachOptions
): string {
  return `${serial}:${viewerId}:${scrcpyAttachProfileKey(options)}`;
}

function scrcpyDetachKey(serial: string, viewerId: string): string {
  return `${serial}:${viewerId}`;
}

function cancelPendingScrcpyDetach(serial: string, viewerId: string): void {
  const key = scrcpyDetachKey(serial, viewerId);
  const timer = pendingScrcpyDetachByViewer.get(key);
  if (!timer) return;
  clearTimeout(timer);
  pendingScrcpyDetachByViewer.delete(key);
}

function hasRecentScrcpyAttach(
  serial: string,
  viewerId: string,
  options?: ScrcpyAttachOptions
): boolean {
  const attachedAt = recentScrcpyAttachByViewer.get(
    scrcpyAttachKey(serial, viewerId, options)
  );
  return (
    attachedAt !== undefined &&
    Date.now() - attachedAt < SCRCPY_ATTACH_DEDUPE_MS
  );
}

function rememberScrcpyAttach(
  serial: string,
  viewerId: string,
  options?: ScrcpyAttachOptions
): void {
  recentScrcpyAttachByViewer.set(
    scrcpyAttachKey(serial, viewerId, options),
    Date.now()
  );
}

function forgetScrcpyAttach(serial: string, viewerId: string): void {
  const prefix = `${serial}:${viewerId}:`;
  recentScrcpyAttachByViewer.forEach((_attachedAt, key) => {
    if (key.startsWith(prefix)) {
      recentScrcpyAttachByViewer.delete(key);
    }
  });
}

function getObjectCoverRect(
  sourceW: number,
  sourceH: number,
  displayW: number,
  displayH: number,
  align: 'center' | 'bottom'
): ObjectFitRect {
  if (sourceW <= 0 || sourceH <= 0 || displayW <= 0 || displayH <= 0) {
    return { left: 0, top: 0, width: displayW, height: displayH, scale: 1 };
  }
  const scale = Math.max(displayW / sourceW, displayH / sourceH);
  const width = sourceW * scale;
  const height = sourceH * scale;
  return {
    left: (displayW - width) / 2,
    top: align === 'bottom' ? displayH - height : (displayH - height) / 2,
    width,
    height,
    scale
  };
}

function getObjectContainRect(
  sourceW: number,
  sourceH: number,
  displayW: number,
  displayH: number,
  align: 'center' | 'bottom'
): ObjectFitRect {
  if (sourceW <= 0 || sourceH <= 0 || displayW <= 0 || displayH <= 0) {
    return { left: 0, top: 0, width: displayW, height: displayH, scale: 1 };
  }
  const scale = Math.min(displayW / sourceW, displayH / sourceH);
  const width = sourceW * scale;
  const height = sourceH * scale;
  return {
    left: (displayW - width) / 2,
    top: align === 'bottom' ? displayH - height : (displayH - height) / 2,
    width,
    height,
    scale
  };
}

interface DeviceScreenProps {
  device: Device;
  wsSend: (obj: object) => void;
  mode: 'tap' | 'swipe';
  onTap?: (rx: number, ry: number) => void;
  /** Normalized 0–1 coords + duration (ms), after a completed swipe drag (not drag mode). */
  onSwipe?: (
    rx1: number,
    ry1: number,
    rx2: number,
    ry2: number,
    durationMs: number
  ) => void;
  /** Normalized 0–1 + duration when gesture mode is drag. */
  onDragGesture?: (
    rx1: number,
    ry1: number,
    rx2: number,
    ry2: number,
    durationMs: number
  ) => void;
  apiBase?: string;
  /** Highlight bounds overlay [x1, y1, x2, y2] in device pixels */
  highlightBounds?: [number, number, number, number] | null;
  /** Gesture mode: tap, swipe, double_tap, drag */
  gestureMode?: 'tap' | 'swipe' | 'double_tap' | 'drag';
  /** Omit app caption row — parent renders it under the mockup for full-height stream. */
  captionBelowFrame?: boolean;
  /** Must match Tailwind object-* on img/canvas so taps map to the visible crop. */
  streamCoverAlign?: 'center' | 'bottom';
  /** Stream fit strategy. `contain` avoids crop on odd aspect-ratio devices. */
  streamFit?: 'cover' | 'contain';
  /** Reports decoded stream dimensions so parent frame can match the actual feed ratio. */
  onStreamSize?: (size: Size) => void;
  /** Read-only preview: disable all interactions with device. */
  interactive?: boolean;
  /** Hint browser to prioritize MJPEG fetch (control-record mirror). */
  streamFetchPriority?: 'high' | 'low' | 'auto';
  /** Stream policy. Control/record uses H264-only to avoid MJPEG screenshot latency. */
  streamTransport?: DeviceScreenTransport;
  /** Optional scrcpy profile for high-priority control surfaces. */
  scrcpyAttachOptions?: ScrcpyAttachOptions;
  /** Stable for this mounted screen; controls backend profile arbitration. */
  scrcpyViewerRole?: ScrcpyViewerRole;
  /**
   * Receives a grabber for the current frame as a PNG data URL, or null when no
   * frame has decoded yet. Lets callers (e.g. cropping a tap_image template)
   * read the pixels already on screen instead of asking the backend for a
   * screenshot — since media moved to go2rtc the backend has no frame to give.
   */
  captureFrameRef?: MutableRefObject<(() => string | null) | null>;
  /**
   * Drag a rectangle on the mirror instead of tapping through to the device —
   * used to cut a tap_image template out of the screen the user is looking at.
   * Ratios are in device space (letterboxing already removed), matching what
   * `captureFrameRef` returns, so callers can crop the grabbed frame directly.
   */
  regionSelect?: RegionSelect;
}

export type RegionSelectRect = {
  rx1: number;
  ry1: number;
  rx2: number;
  ry2: number;
};

export type RegionSelect = {
  active: boolean;
  onComplete: (rect: RegionSelectRect) => void;
  onCancel: () => void;
  /** Shown over the mirror while selecting. */
  hint?: string;
  /**
   * Still frame to drag on, pinned when selection started.
   *
   * Without it the user drags over a live stream and the caller crops a frame
   * grabbed after the drag — a different moment, so the cut content does not
   * match what was under the selection. Freezing makes what you see the thing
   * you cut. Rendered with the same object-fit as the stream so the ratios
   * `clientToDevice` produces address the same pixels.
   */
  frozenFrame?: string | null;
};

export function DeviceScreen({
  device,
  wsSend,
  mode,
  onTap,
  onSwipe,
  onDragGesture,
  highlightBounds,
  gestureMode,
  captionBelowFrame = false,
  streamCoverAlign = 'bottom',
  streamFit,
  onStreamSize,
  interactive = true,
  streamFetchPriority = 'auto',
  streamTransport = 'auto',
  scrcpyAttachOptions,
  scrcpyViewerRole = 'control-screen',
  captureFrameRef,
  regionSelect
}: DeviceScreenProps) {
  const t = useTranslations('devicesFarm');
  const pathname = usePathname();
  const ownerPathnameRef = useRef(pathname);
  const routeActive = pathname === ownerPathnameRef.current;
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const draggedRef = useRef(false);
  const dragStartRef = useRef<{ x: number; y: number } | null>(null);
  const onSwipeRef = useRef(onSwipe);
  const onDragGestureRef = useRef(onDragGesture);
  onSwipeRef.current = onSwipe;
  onDragGestureRef.current = onDragGesture;
  const [hasFrame, setHasFrame] = useState(false);
  const hasFrameRef = useRef(false);
  const [mjpegFailed, setMjpegFailed] = useState(false);
  const [mjpegAttempt, setMjpegAttempt] = useState(0);
  const [wsConnected, setWsConnected] = useState(false);
  const [wsConnectedGeneration, setWsConnectedGeneration] = useState(0);
  const [loadingElapsedSec, setLoadingElapsedSec] = useState(0);
  const [streamSize, setStreamSize] = useState<Size | null>(null);
  const [wrapSize, setWrapSize] = useState<Size>({ width: 0, height: 0 });

  const id = serialToId(device.serial);
  const dw = device.screen_width || 1080;
  const dh = device.screen_height || 1920;

  const isActive =
    device.state &&
    !['DISCONNECTED', 'DEAD'].includes(device.state.toUpperCase());

  const isUnresponsive = isActive && !hasFrame && loadingElapsedSec >= 12;

  // Track whether jmuxer has delivered at least one H264 frame
  const [h264Active, setH264Active] = useState(false);
  const h264TimeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(
    null
  );
  const h264StableTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(
    null
  );
  const h264StallFallbackTimerRef = React.useRef<ReturnType<
    typeof setTimeout
  > | null>(null);
  const h264WarmupRef = React.useRef<{ startedAt: number; frames: number }>({
    startedAt: 0,
    frames: 0
  });
  const h264RecoveryBurstRef = React.useRef<{ firstAt: number; count: number }>(
    { firstAt: 0, count: 0 }
  );
  const h264BlackStreakRef = React.useRef(0);
  const h264Only = streamTransport === 'h264-only';
  const webrtcRequested = streamTransport === 'webrtc';
  const [scrcpyAttachReady, setScrcpyAttachReady] = useState(false);
  const h264TransportAllowed = !webrtcRequested;
  const mjpegAllowed = !h264Only && h264TransportAllowed;
  const [mjpegEnabled, setMjpegEnabled] = useState(mjpegAllowed);
  const [h264Stalled, setH264Stalled] = useState(false);
  const [h264Suppressed, setH264Suppressed] = useState(false);
  const [h264RestartKey, setH264RestartKey] = useState(0);
  const lastInputIdrRef = useRef(0);
  const h264RenderedFrameVersionRef = useRef(0);
  const inputRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  );
  const initialFrameRefreshTimersRef = useRef<ReturnType<typeof setTimeout>[]>(
    []
  );

  const clearInitialFrameRefreshTimers = useCallback(() => {
    initialFrameRefreshTimersRef.current.forEach((timer) =>
      clearTimeout(timer)
    );
    initialFrameRefreshTimersRef.current = [];
  }, []);

  const requestInitialFrameRefresh = useCallback(
    (serial: string) => {
      clearInitialFrameRefreshTimers();
      const delays = [350, 1000, 2200, 3500];
      initialFrameRefreshTimersRef.current = delays.map((delay) =>
        setTimeout(() => {
          if (hasFrameRef.current) return;
          if (attachedScrcpySerialRef.current !== serial) return;
          ensureWatchSerial(serial);
          requestIdr(serial, 0);
        }, delay)
      );
    },
    [clearInitialFrameRefreshTimers]
  );

  useEffect(() => {
    hasFrameRef.current = hasFrame;
    if (hasFrame) clearInitialFrameRefreshTimers();
  }, [clearInitialFrameRefreshTimers, hasFrame]);

  useEffect(
    () => () => {
      clearInitialFrameRefreshTimers();
      if (inputRefreshTimerRef.current) {
        clearTimeout(inputRefreshTimerRef.current);
        inputRefreshTimerRef.current = null;
      }
    },
    [clearInitialFrameRefreshTimers]
  );

  const [streamingFlags, setStreamingFlags] = useState<StreamingFlags | null>(
    cachedStreamingFlags
  );
  const [screenStreamOn, setScreenStreamOn] = useState(true);
  const [streamToggleBusy, setStreamToggleBusy] = useState(false);
  const [scrcpyAttachRetryTick, setScrcpyAttachRetryTick] = useState(0);
  const attachedScrcpySerialRef = useRef<string | null>(null);
  const pendingScrcpyAttachSerialRef = useRef<string | null>(null);
  const attachedScrcpyWsGenerationRef = useRef<number | null>(null);
  const scrcpyAttachGenerationRef = useRef(0);
  const scrcpyAttachRetryTimerRef = useRef<ReturnType<
    typeof setTimeout
  > | null>(null);
  const tabActive = useTabNetworkActive();
  const streamingMode = streamingFlags?.mode;
  const streamingAutoAttach = streamingFlags?.autoAttach;
  const scrcpyViewerSessionRef = useRef<ReturnType<
    typeof createScrcpyViewerSession
  > | null>(null);
  if (scrcpyViewerSessionRef.current === null) {
    scrcpyViewerSessionRef.current =
      createScrcpyViewerSession(scrcpyViewerRole);
  }
  const scrcpyViewerIdForSerial = useCallback(
    (serial: string) => scrcpyViewerSessionRef.current!.idFor(serial),
    []
  );

  const clearScrcpyAttachRetryTimer = useCallback(() => {
    if (scrcpyAttachRetryTimerRef.current) {
      clearTimeout(scrcpyAttachRetryTimerRef.current);
      scrcpyAttachRetryTimerRef.current = null;
    }
  }, []);

  const scheduleScrcpyAttachRetry = useCallback(
    (generation: number, serial: string) => {
      clearScrcpyAttachRetryTimer();
      scrcpyAttachRetryTimerRef.current = setTimeout(() => {
        scrcpyAttachRetryTimerRef.current = null;
        if (scrcpyAttachGenerationRef.current !== generation) return;
        if (attachedScrcpySerialRef.current !== null) return;
        if (pendingScrcpyAttachSerialRef.current !== null) return;
        if (serial !== device.serial) return;
        setScrcpyAttachRetryTick((tick) => tick + 1);
      }, SCRCPY_ATTACH_RETRY_MS);
    },
    [clearScrcpyAttachRetryTimer, device.serial]
  );

  const detachScrcpyViewer = useCallback(
    (...serials: Array<string | null>) => {
      Array.from(new Set(serials.filter(Boolean) as string[])).forEach(
        (serial) => {
          const viewerId = scrcpyViewerIdForSerial(serial);
          cancelPendingScrcpyDetach(serial, viewerId);
          forgetScrcpyAttach(serial, viewerId);
          detachScrcpyStream(serial, viewerId).catch(() => {});
        }
      );
    },
    [scrcpyViewerIdForSerial]
  );

  const scheduleScrcpyViewerDetach = useCallback(
    (...serials: Array<string | null>) => {
      Array.from(new Set(serials.filter(Boolean) as string[])).forEach(
        (serial) => {
          const viewerId = scrcpyViewerIdForSerial(serial);
          cancelPendingScrcpyDetach(serial, viewerId);
          const timer = setTimeout(() => {
            pendingScrcpyDetachByViewer.delete(
              scrcpyDetachKey(serial, viewerId)
            );
            forgetScrcpyAttach(serial, viewerId);
            detachScrcpyStream(serial, viewerId).catch(() => {});
          }, SCRCPY_TRANSIENT_UNMOUNT_DETACH_DELAY_MS);
          pendingScrcpyDetachByViewer.set(
            scrcpyDetachKey(serial, viewerId),
            timer
          );
        }
      );
    },
    [scrcpyViewerIdForSerial]
  );

  const updateStreamSize = useCallback(
    (width: number, height: number) => {
      if (
        !Number.isFinite(width) ||
        !Number.isFinite(height) ||
        width <= 0 ||
        height <= 0
      )
        return;
      const next = { width: Math.round(width), height: Math.round(height) };
      setStreamSize((prev) =>
        prev?.width === next.width && prev?.height === next.height ? prev : next
      );
      onStreamSize?.(next);
    },
    [onStreamSize]
  );

  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const update = () => {
      const rect = el.getBoundingClientRect();
      setWrapSize((prev) => {
        const width = Math.round(rect.width);
        const height = Math.round(rect.height);
        return prev.width === width && prev.height === height
          ? prev
          : { width, height };
      });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadStreamingFlags().then((res) => {
      if (cancelled) return;
      setStreamingFlags(res);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  /** Sync from server (default on). Control page always streams when relay toggle is hidden. */
  useLayoutEffect(() => {
    if (!streamingMode) return;
    if (streamingMode !== 'continuous') {
      setScreenStreamOn((prev) => (prev ? prev : true));
      return;
    }
    if (!SHOW_RELAY_SCRCPY_UI_TOGGLE) {
      setScreenStreamOn((prev) => (prev ? prev : true));
      return;
    }
    const serverWants =
      device.relay_scrcpy_enabled !== undefined &&
      device.relay_scrcpy_enabled !== null
        ? Boolean(device.relay_scrcpy_enabled)
        : Boolean(streamingAutoAttach ?? true);
    setScreenStreamOn((prev) => (prev === serverWants ? prev : serverWants));
  }, [
    streamingMode,
    streamingAutoAttach,
    device.serial,
    device.relay_scrcpy_enabled
  ]);

  // Until /api/config returns, assume non-continuous (fail-open: keep legacy full stream).
  const isContinuous =
    streamingFlags !== null && streamingMode === 'continuous';
  /** Subscribe relay H.264 + honor server detach; transport policy controls MJPEG fallback. */
  const relayH264Allowed =
    streamingFlags === null || !isContinuous || screenStreamOn;
  const h264DecodeAllowed =
    h264TransportAllowed && relayH264Allowed && (h264Only || !h264Suppressed);
  // Keep the control-page WS watcher alive while scrcpy attach/retry is in flight.
  // Gating subscription on attach readiness can drop the only subscriber during a
  // backend restart, leaving scrcpy frames queued to 0 frontend subscribers.
  const h264SubscriptionAllowed = h264TransportAllowed && relayH264Allowed;
  const h264PrimaryMode = isContinuous && h264DecodeAllowed;

  useEffect(() => {
    if (!h264SubscriptionAllowed) clearInitialFrameRefreshTimers();
  }, [clearInitialFrameRefreshTimers, h264SubscriptionAllowed]);

  useEffect(() => {
    setScrcpyAttachReady(false);
  }, [device.serial, streamTransport]);

  const handleWebRtcFrame = useCallback(() => {
    h264RenderedFrameVersionRef.current += 1;
    if (!hasFrameRef.current) {
      setHasFrame(true);
    }
  }, []);

  const handleWebRtcError = useCallback(() => {
    setHasFrame(false);
  }, []);

  const handleH264Size = useCallback(
    (size: { width: number; height: number }) => {
      updateStreamSize(size.width, size.height);
    },
    [updateStreamSize]
  );

  const webrtc = useWebRtcVideo(device.serial, videoRef, {
    enabled:
      webrtcRequested &&
      scrcpyAttachReady &&
      routeActive &&
      tabActive &&
      Boolean(isActive),
    control: scrcpyAttachOptions?.enableControl,
    profile: scrcpyAttachOptions?.profile,
    maxFps: scrcpyAttachOptions?.maxFps,
    maxWidth: scrcpyAttachOptions?.maxWidth,
    bitrate: scrcpyAttachOptions?.bitrate,
    onFrame: handleWebRtcFrame,
    onSize: updateStreamSize,
    onError: handleWebRtcError
  });

  // Control is an explicit viewer: always ask the backend to attach scrcpy in
  // continuous mode. If auto-attach is disabled server-side, this starts video;
  // if it is already running, the backend treats it as idempotent.
  useEffect(() => {
    const onPageHide = () => {
      const attachedSerial = attachedScrcpySerialRef.current;
      const pendingSerial = pendingScrcpyAttachSerialRef.current;
      if (!attachedSerial && !pendingSerial) return;
      scrcpyAttachGenerationRef.current += 1;
      attachedScrcpySerialRef.current = null;
      pendingScrcpyAttachSerialRef.current = null;
      attachedScrcpyWsGenerationRef.current = null;
      clearScrcpyAttachRetryTimer();
      Array.from(
        new Set([attachedSerial, pendingSerial].filter(Boolean) as string[])
      ).forEach((serial) => {
        const viewerId = scrcpyViewerIdForSerial(serial);
        cancelPendingScrcpyDetach(serial, viewerId);
        forgetScrcpyAttach(serial, viewerId);
        detachScrcpyStreamOnPageHide(serial, viewerId).catch(() => {});
      });
    };
    window.addEventListener('pagehide', onPageHide);
    return () => {
      window.removeEventListener('pagehide', onPageHide);
    };
  }, [clearScrcpyAttachRetryTimer, scrcpyViewerIdForSerial]);

  useEffect(() => {
    return () => {
      const attachedSerial = attachedScrcpySerialRef.current;
      const pendingSerial = pendingScrcpyAttachSerialRef.current;
      if (!attachedSerial && !pendingSerial) return;
      scrcpyAttachGenerationRef.current += 1;
      attachedScrcpySerialRef.current = null;
      pendingScrcpyAttachSerialRef.current = null;
      attachedScrcpyWsGenerationRef.current = null;
      clearScrcpyAttachRetryTimer();
      scheduleScrcpyViewerDetach(attachedSerial, pendingSerial);
    };
  }, [clearScrcpyAttachRetryTimer, scheduleScrcpyViewerDetach]);

  useEffect(() => {
    if (webrtcRequested) {
      clearInitialFrameRefreshTimers();
      clearScrcpyAttachRetryTimer();
      const attachedSerial = attachedScrcpySerialRef.current;
      const pendingSerial = pendingScrcpyAttachSerialRef.current;
      scrcpyAttachGenerationRef.current += 1;
      attachedScrcpySerialRef.current = null;
      pendingScrcpyAttachSerialRef.current = null;
      attachedScrcpyWsGenerationRef.current = null;
      detachScrcpyViewer(attachedSerial, pendingSerial);
      setScrcpyAttachReady(
        routeActive && tabActive && Boolean(isActive) && screenStreamOn
      );
      return;
    }
    const shouldAttach =
      routeActive &&
      tabActive &&
      (streamingFlags === null || isContinuous) &&
      isActive &&
      screenStreamOn;
    if (!shouldAttach) {
      setScrcpyAttachReady(false);
      clearInitialFrameRefreshTimers();
      clearScrcpyAttachRetryTimer();
      const attachedSerial = attachedScrcpySerialRef.current;
      const pendingSerial = pendingScrcpyAttachSerialRef.current;
      scrcpyAttachGenerationRef.current += 1;
      attachedScrcpySerialRef.current = null;
      pendingScrcpyAttachSerialRef.current = null;
      attachedScrcpyWsGenerationRef.current = null;
      if (routeActive && !tabActive) {
        scheduleScrcpyViewerDetach(attachedSerial, pendingSerial);
      } else {
        detachScrcpyViewer(attachedSerial, pendingSerial);
      }
      return;
    }

    const serial = device.serial;
    const viewerId = scrcpyViewerIdForSerial(serial);
    cancelPendingScrcpyDetach(serial, viewerId);
    if (
      attachedScrcpySerialRef.current === serial &&
      pendingScrcpyAttachSerialRef.current !== serial
    ) {
      setScrcpyAttachReady(true);
      if (
        h264SubscriptionAllowed &&
        attachedScrcpyWsGenerationRef.current !== wsConnectedGeneration
      ) {
        attachedScrcpyWsGenerationRef.current = wsConnectedGeneration;
        ensureWatchSerial(serial);
        requestInitialFrameRefresh(serial);
        requestIdr(serial);
      }
      return;
    }
    clearScrcpyAttachRetryTimer();
    const previousSerial = attachedScrcpySerialRef.current;
    if (previousSerial && previousSerial !== serial) {
      detachScrcpyViewer(previousSerial);
    }
    setScrcpyAttachReady(false);
    const generation = scrcpyAttachGenerationRef.current + 1;
    scrcpyAttachGenerationRef.current = generation;
    pendingScrcpyAttachSerialRef.current = serial;
    attachedScrcpySerialRef.current = serial;
    attachedScrcpyWsGenerationRef.current = wsConnectedGeneration;

    if (h264SubscriptionAllowed) {
      ensureWatchSerial(serial);
      requestIdr(serial, 0);
    }
    if (hasRecentScrcpyAttach(serial, viewerId, scrcpyAttachOptions)) {
      pendingScrcpyAttachSerialRef.current = null;
      setScrcpyAttachReady(true);
      if (h264SubscriptionAllowed) {
        ensureWatchSerial(serial);
        requestInitialFrameRefresh(serial);
        requestIdr(serial);
      }
      return;
    }
    attachScrcpyStream(serial, viewerId, scrcpyAttachOptions)
      .then(() => {
        clearScrcpyAttachRetryTimer();
        pendingScrcpyAttachSerialRef.current =
          pendingScrcpyAttachSerialRef.current === serial
            ? null
            : pendingScrcpyAttachSerialRef.current;
        if (
          scrcpyAttachGenerationRef.current !== generation ||
          attachedScrcpySerialRef.current !== serial
        ) {
          if (attachedScrcpySerialRef.current !== serial) {
            detachScrcpyViewer(serial);
          }
          return;
        }
        if (h264SubscriptionAllowed) {
          ensureWatchSerial(serial);
        }
        rememberScrcpyAttach(serial, viewerId, scrcpyAttachOptions);
        setScrcpyAttachReady(true);
        setMjpegFailed(false);
        setMjpegAttempt((n) => n + 1);
        setH264Suppressed(false);
        if (h264SubscriptionAllowed) {
          requestInitialFrameRefresh(serial);
          requestIdr(serial);
        }
      })
      .catch((err) => {
        if (
          scrcpyAttachGenerationRef.current === generation &&
          attachedScrcpySerialRef.current === serial
        ) {
          setScrcpyAttachReady(false);
          attachedScrcpySerialRef.current = null;
          pendingScrcpyAttachSerialRef.current = null;
          attachedScrcpyWsGenerationRef.current = null;
        } else if (pendingScrcpyAttachSerialRef.current === serial) {
          pendingScrcpyAttachSerialRef.current = null;
          return;
        }
        if (isScrcpyAttachCancellation(err)) return;
        if (!isRecoverableScrcpyAttachError(err)) {
          const msg = scrcpyAttachErrorMessage(err);
          toast.error(t('screenStreamAttachError'), {
            description: msg || undefined
          });
        }
        scheduleScrcpyAttachRetry(generation, serial);
      });

    return () => {
      // Do not detach on React effect re-runs (config load, screenStreamOn sync).
      // Server auto-stops after idle; pagehide handles tab close / navigation.
    };
  }, [
    clearInitialFrameRefreshTimers,
    clearScrcpyAttachRetryTimer,
    detachScrcpyViewer,
    device.serial,
    isActive,
    isContinuous,
    h264SubscriptionAllowed,
    requestInitialFrameRefresh,
    routeActive,
    scheduleScrcpyAttachRetry,
    scheduleScrcpyViewerDetach,
    scrcpyAttachRetryTick,
    scrcpyViewerIdForSerial,
    screenStreamOn,
    scrcpyAttachOptions,
    streamingFlags,
    tabActive,
    t,
    wsConnected,
    wsConnectedGeneration,
    webrtcRequested
  ]);

  const onScreenStreamChange = useCallback(
    async (checked: boolean) => {
      if (!isContinuous || !isActive) return;
      if (webrtcRequested) {
        setScreenStreamOn(checked);
        if (!checked) {
          setHasFrame(false);
        }
        return;
      }
      setStreamToggleBusy(true);
      const toggleSerial = device.serial;
      const toggleViewerId = scrcpyViewerIdForSerial(toggleSerial);
      let toggleGeneration: number | null = null;
      try {
        if (checked) {
          const generation = scrcpyAttachGenerationRef.current + 1;
          toggleGeneration = generation;
          scrcpyAttachGenerationRef.current = generation;
          pendingScrcpyAttachSerialRef.current = toggleSerial;
          attachedScrcpySerialRef.current = toggleSerial;
          attachedScrcpyWsGenerationRef.current = wsConnectedGeneration;
          if (
            !hasRecentScrcpyAttach(
              toggleSerial,
              toggleViewerId,
              scrcpyAttachOptions
            )
          ) {
            await attachScrcpyStream(
              toggleSerial,
              toggleViewerId,
              scrcpyAttachOptions
            );
            rememberScrcpyAttach(
              toggleSerial,
              toggleViewerId,
              scrcpyAttachOptions
            );
          }
          if (
            hasRecentScrcpyAttach(
              toggleSerial,
              toggleViewerId,
              scrcpyAttachOptions
            )
          ) {
            pendingScrcpyAttachSerialRef.current = null;
            attachedScrcpySerialRef.current = toggleSerial;
            attachedScrcpyWsGenerationRef.current = wsConnectedGeneration;
          }
          pendingScrcpyAttachSerialRef.current =
            pendingScrcpyAttachSerialRef.current === toggleSerial
              ? null
              : pendingScrcpyAttachSerialRef.current;
          if (
            scrcpyAttachGenerationRef.current !== generation ||
            attachedScrcpySerialRef.current !== toggleSerial
          ) {
            detachScrcpyViewer(toggleSerial);
            return;
          }
          attachedScrcpySerialRef.current = toggleSerial;
          attachedScrcpyWsGenerationRef.current = wsConnectedGeneration;
        } else {
          const attachedSerial = attachedScrcpySerialRef.current;
          const pendingSerial = pendingScrcpyAttachSerialRef.current;
          scrcpyAttachGenerationRef.current += 1;
          attachedScrcpySerialRef.current = null;
          pendingScrcpyAttachSerialRef.current = null;
          attachedScrcpyWsGenerationRef.current = null;
          await Promise.all(
            Array.from(
              new Set(
                [toggleSerial, attachedSerial, pendingSerial].filter(
                  Boolean
                ) as string[]
              )
            ).map((serial) => {
              const viewerId = scrcpyViewerIdForSerial(serial);
              return detachScrcpyStream(serial, viewerId)
                .then(() => forgetScrcpyAttach(serial, viewerId))
                .catch(() => {});
            })
          );
        }
        setScreenStreamOn(checked);
        if (!checked) {
          setHasFrame(false);
          setH264Active(false);
          setH264Stalled(false);
          setH264Suppressed(false);
          setH264RestartKey((key) => key + 1);
          setMjpegEnabled(false);
        } else {
          setH264Stalled(false);
          setH264Suppressed(false);
          setH264RestartKey((key) => key + 1);
          setMjpegEnabled(mjpegAllowed);
        }
      } catch (err) {
        if (
          checked &&
          toggleGeneration !== null &&
          scrcpyAttachGenerationRef.current === toggleGeneration &&
          attachedScrcpySerialRef.current === toggleSerial
        ) {
          attachedScrcpySerialRef.current = null;
          pendingScrcpyAttachSerialRef.current = null;
          attachedScrcpyWsGenerationRef.current = null;
        }
        const msg = scrcpyAttachErrorMessage(err);
        toast.error(
          checked ? t('screenStreamAttachError') : t('screenStreamDetachError'),
          { description: msg || undefined }
        );
      } finally {
        setStreamToggleBusy(false);
      }
    },
    [
      detachScrcpyViewer,
      device.serial,
      isActive,
      isContinuous,
      mjpegAllowed,
      scrcpyAttachOptions,
      scrcpyViewerIdForSerial,
      t,
      webrtcRequested,
      wsConnectedGeneration
    ]
  );

  // In auto transport, keep MJPEG visible until H264 is actually rendering.
  // Otherwise the canvas can be black during decoder warm-up or IDR recovery.
  const mjpegUrl = React.useMemo(() => {
    if (!routeActive) return null;
    if (!mjpegAllowed) return null;
    if (!tabActive) return null;
    if (!isActive || !mjpegEnabled) return null;
    if (h264PrimaryMode && h264Active && !h264Stalled) return null;
    const fps = h264PrimaryMode ? 5 : 30;
    const base = `${deviceFarmMediaBase}/stream/${encodeURIComponent(device.serial)}?fps=${fps}`;
    const token = tokenStorage.getAuthToken();
    const withAuth = token
      ? `${base}&token=${encodeURIComponent(token)}`
      : base;
    return mjpegAttempt > 0 ? `${withAuth}&_r=${mjpegAttempt}` : withAuth;
  }, [
    isActive,
    tabActive,
    mjpegEnabled,
    mjpegAttempt,
    device.serial,
    h264PrimaryMode,
    h264Active,
    h264Stalled,
    mjpegAllowed,
    routeActive
  ]);

  useEffect(() => {
    setMjpegFailed(false);
  }, [mjpegUrl]);

  useEffect(() => {
    if (
      !mjpegAllowed ||
      !mjpegFailed ||
      !tabActive ||
      !isActive ||
      !mjpegEnabled
    )
      return;
    const retry = window.setTimeout(() => {
      setMjpegFailed(false);
      setMjpegAttempt((n) => n + 1);
    }, 3000);
    return () => window.clearTimeout(retry);
  }, [isActive, mjpegAllowed, mjpegEnabled, mjpegFailed, tabActive]);

  // Always pass real serial so binary frames are subscribed immediately on mount.
  // H264-only surfaces intentionally skip the MJPEG screenshot fallback.
  useH264Video(
    routeActive && tabActive && isActive && h264SubscriptionAllowed
      ? device.serial
      : '',
    canvasRef,
    {
      restartKey: h264RestartKey,
      inspectFramesForBlack: !h264Only,
      visibleFrameRecoveryMinIntervalMs: h264PrimaryMode
        ? H264_PRIMARY_VISIBLE_RECOVERY_MIN_MS
        : 3000,
      renderedFrameStaleMs: h264PrimaryMode ? 2000 : 5000,
      onSize: handleH264Size,
      onFrame: useCallback(
        (frame?: { mostlyBlack: boolean }) => {
          h264RenderedFrameVersionRef.current += 1;
          const canvas = canvasRef.current;
          if (canvas?.width && canvas?.height) {
            updateStreamSize(canvas.width, canvas.height);
          }
          if (h264StallFallbackTimerRef.current) {
            clearTimeout(h264StallFallbackTimerRef.current);
            h264StallFallbackTimerRef.current = null;
          }
          if (frame?.mostlyBlack) {
            if (h264PrimaryMode) {
              h264BlackStreakRef.current = 0;
              if (!hasFrame) setHasFrame(true);
            } else {
              // Decoder reset/IDR often emits 1–2 black frames. Hiding H264
              // immediately makes control-record mirror flash on every tap.
              if (h264Active || hasFrame) {
                h264BlackStreakRef.current += 1;
                if (h264BlackStreakRef.current < 4) return;
              }
              setH264Active(false);
              setH264Stalled(true);
              h264WarmupRef.current = { startedAt: 0, frames: 0 };
              return;
            }
          }
          h264BlackStreakRef.current = 0;
          if (!hasFrame) setHasFrame(true);

          // Once a frame has rendered, the canvas is no longer black. Switch back
          // to H264 immediately; staying on low-FPS MJPEG makes the stream feel
          // frozen even though the decoder has recovered.
          const now = Date.now();
          const warm = h264WarmupRef.current;
          if (warm.startedAt === 0 || now - warm.startedAt > 1500) {
            warm.startedAt = now;
            warm.frames = 1;
          } else {
            warm.frames += 1;
          }
          if (!h264Active && warm.frames >= 1) {
            setH264Active(true);
            if (h264Stalled) setH264Stalled(false);
          }

          // In H264-primary mode, keep showing the last decoded frame on static scenes.
          // Some devices emit very few frames while idle; timing out to "inactive"
          // causes a false black screen even though stream is still healthy.
          if (h264PrimaryMode) {
            if (h264TimeoutRef.current) {
              clearTimeout(h264TimeoutRef.current);
              h264TimeoutRef.current = null;
            }
          } else {
            if (h264TimeoutRef.current) clearTimeout(h264TimeoutRef.current);
            h264TimeoutRef.current = setTimeout(
              () => setH264Active(false),
              8000
            );
          }
        },
        [hasFrame, h264Active, h264PrimaryMode, h264Stalled, updateStreamSize]
      ),
      onStall: useCallback(
        (reason: 'no_packets' | 'decoder_stalled') => {
          const now = Date.now();
          const burst = h264RecoveryBurstRef.current;
          if (burst.firstAt === 0 || now - burst.firstAt > 45_000) {
            burst.firstAt = now;
            burst.count = 1;
          } else {
            burst.count += 1;
          }
          if (reason === 'decoder_stalled' && hasFrame) {
            // The hook already resets WebCodecs and requests a fresh IDR. Keep the
            // last good canvas visible so recovery does not flash between H264/MJPEG.
            setH264Stalled(true);
            h264WarmupRef.current = { startedAt: 0, frames: 0 };
            if (h264StallFallbackTimerRef.current) {
              clearTimeout(h264StallFallbackTimerRef.current);
              h264StallFallbackTimerRef.current = null;
            }
            if (h264PrimaryMode || h264Only) {
              setH264Active(true);
              setHasFrame(true);
              setMjpegEnabled(false);
            } else {
              setMjpegEnabled(mjpegAllowed);
              h264StallFallbackTimerRef.current = setTimeout(() => {
                setH264Active(false);
                setHasFrame(false);
              }, 3000);
            }
            return;
          }
          setH264Stalled(true);
          h264WarmupRef.current = { startedAt: 0, frames: 0 };
          // Remounting the worker clears sticky hardware-fallback state and
          // recreates black-screen gaps. Prefer IDR recovery in-place for
          // H264-primary / H264-only surfaces (control + monitor).
          if (h264PrimaryMode || h264Only) {
            setH264Active(true);
            if (hasFrame) setHasFrame(true);
            setMjpegEnabled(false);
            requestIdr(device.serial, 0);
            return;
          }
          setH264Active(false);
          setH264RestartKey((key) => key + 1);
          setHasFrame(false);
          setMjpegEnabled(mjpegAllowed);
          if (burst.count >= 3) {
            burst.firstAt = now;
            burst.count = 0;
            setH264Suppressed(false);
            setH264RestartKey((key) => key + 1);
            requestIdr(device.serial, 0);
          }
        },
        [device.serial, h264Only, h264PrimaryMode, hasFrame, mjpegAllowed]
      )
    }
  );

  // Reset h264Active when device changes or goes offline
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d', {
      alpha: false,
      desynchronized: true
    });
    if (canvas && ctx) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    if (imageRef.current) {
      imageRef.current.removeAttribute('src');
    }
    setHasFrame(false);
    setH264Active(false);
    setH264Stalled(false);
    setH264Suppressed(false);
    h264RecoveryBurstRef.current = { firstAt: 0, count: 0 };
    h264BlackStreakRef.current = 0;
    setH264RestartKey((key) => key + 1);
    setLoadingElapsedSec(0);
    setStreamSize(null);
    setMjpegFailed(false);
    setMjpegAttempt(0);
    setMjpegEnabled(mjpegAllowed);
    h264WarmupRef.current = { startedAt: 0, frames: 0 };
    clearInitialFrameRefreshTimers();
    if (inputRefreshTimerRef.current) {
      clearTimeout(inputRefreshTimerRef.current);
      inputRefreshTimerRef.current = null;
    }
    if (h264TimeoutRef.current) clearTimeout(h264TimeoutRef.current);
    if (h264StableTimerRef.current) clearTimeout(h264StableTimerRef.current);
    if (h264StallFallbackTimerRef.current)
      clearTimeout(h264StallFallbackTimerRef.current);
  }, [
    clearInitialFrameRefreshTimers,
    device.serial,
    isActive,
    mjpegAllowed,
    relayH264Allowed
  ]);

  // Once H264 is rendering, stop MJPEG network fetches entirely. Until then,
  // MJPEG remains the visible baseline so the user does not see a black canvas.
  useEffect(() => {
    if (!mjpegAllowed) {
      setMjpegEnabled((prev) => (prev ? false : prev));
      return;
    }
    if (h264PrimaryMode) {
      const next = !h264Active || h264Stalled;
      setMjpegEnabled((prev) => (prev === next ? prev : next));
      return;
    }
    if (!isActive) {
      setMjpegEnabled((prev) => (prev ? false : prev));
      return;
    }
    if (!relayH264Allowed) {
      if (h264StableTimerRef.current) clearTimeout(h264StableTimerRef.current);
      setMjpegEnabled((prev) => (prev ? prev : true));
      return;
    }
    if (h264Active) {
      if (h264StableTimerRef.current) clearTimeout(h264StableTimerRef.current);
      h264StableTimerRef.current = setTimeout(() => {
        setMjpegEnabled((prev) => (prev ? false : prev));
      }, 2000);
    } else {
      if (h264StableTimerRef.current) clearTimeout(h264StableTimerRef.current);
      setMjpegEnabled((prev) => (prev ? prev : true));
    }
    return () => {
      if (h264StableTimerRef.current) clearTimeout(h264StableTimerRef.current);
    };
  }, [
    isActive,
    h264Active,
    relayH264Allowed,
    h264PrimaryMode,
    h264Stalled,
    mjpegAllowed
  ]);

  // Track shared WS connectivity so loading UI can distinguish
  // "socket not up yet" vs "stream waiting first frame".
  useEffect(() => {
    if (!tabActive) {
      setWsConnected(false);
      return;
    }
    const unsub = subscribeDeviceFarm((msg) => {
      if (msg.type === 'ws_status') {
        const connected = Boolean(msg.connected);
        setWsConnected(connected);
        if (connected) setWsConnectedGeneration((value) => value + 1);
      }
    });
    return () => unsub();
  }, [tabActive]);

  // Loading elapsed timer while waiting first frame.
  useEffect(() => {
    if (!isActive || hasFrame) {
      setLoadingElapsedSec(0);
      return;
    }
    const startedAt = Date.now();
    const t = setInterval(() => {
      setLoadingElapsedSec(Math.floor((Date.now() - startedAt) / 1000));
    }, 500);
    return () => clearInterval(t);
  }, [isActive, hasFrame, device.serial]);

  // When WS connects after mount, (re)assert watch + IDR so the mirror is not
  // blank until a full page refresh. Also re-arm MJPEG fallback in H264-primary mode.
  useEffect(() => {
    if (!isActive || !wsConnected || hasFrame || !h264SubscriptionAllowed)
      return;
    ensureWatchSerial(device.serial);
    requestInitialFrameRefresh(device.serial);
    const armMjpeg =
      h264PrimaryMode && mjpegAllowed
        ? setTimeout(() => {
            setMjpegEnabled(true);
            setMjpegFailed(false);
          }, 2500)
        : undefined;
    return () => {
      if (armMjpeg) clearTimeout(armMjpeg);
    };
  }, [
    isActive,
    h264PrimaryMode,
    h264SubscriptionAllowed,
    hasFrame,
    device.serial,
    requestInitialFrameRefresh,
    wsConnected,
    mjpegAllowed
  ]);

  // ── Touch / gesture ──────────────────────────────────────────────────────
  const getCoordinateSpace = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imageRef.current;
    const sourceW =
      (h264Active && canvas?.width ? canvas.width : 0) ||
      img?.naturalWidth ||
      streamSize?.width ||
      dw;
    const sourceH =
      (h264Active && canvas?.height ? canvas.height : 0) ||
      img?.naturalHeight ||
      streamSize?.height ||
      dh;
    let targetW = dw;
    let targetH = dh;

    // Stream frames are the most reliable source for orientation. Status
    // dimensions can lag after rotation, so swap only when orientation differs.
    if (sourceW > 0 && sourceH > 0 && targetW > 0 && targetH > 0) {
      const streamLandscape = sourceW > sourceH;
      const targetLandscape = targetW > targetH;
      if (streamLandscape !== targetLandscape) {
        [targetW, targetH] = [targetH, targetW];
      }
    }

    return {
      sourceW: Math.max(1, sourceW || targetW || 1),
      sourceH: Math.max(1, sourceH || targetH || 1),
      targetW: Math.max(1, targetW || sourceW || 1),
      targetH: Math.max(1, targetH || sourceH || 1)
    };
  }, [dh, dw, h264Active, streamSize]);

  const resolvedStreamFit = React.useMemo<'cover' | 'contain'>(() => {
    if (streamFit) return streamFit;
    // Auto: if aspect ratio differs a lot, prefer contain to avoid aggressive crop.
    const { sourceW, sourceH } = getCoordinateSpace();
    if (wrapSize.width <= 0 || wrapSize.height <= 0) return 'cover';
    if (sourceW <= 0 || sourceH <= 0) return 'cover';
    const r1 = wrapSize.width / wrapSize.height;
    const r2 = sourceW / sourceH;
    const diff = Math.abs(Math.log(r1 / r2));
    return diff > 0.16 ? 'contain' : 'cover';
  }, [getCoordinateSpace, streamFit, wrapSize.height, wrapSize.width]);

  // When we choose `contain`, align center to avoid a "pushed down" look
  // (black bars should be symmetric for best UX).
  const resolvedAlign = React.useMemo<'center' | 'bottom'>(() => {
    return resolvedStreamFit === 'contain' ? 'center' : streamCoverAlign;
  }, [resolvedStreamFit, streamCoverAlign]);

  /** Mirror CSS object-fit exactly, then convert stream ratio to device pixels. */
  const clientToDevice = useCallback(
    (
      displayX: number,
      displayY: number,
      displayW: number,
      displayH: number
    ) => {
      const { sourceW, sourceH, targetW, targetH } = getCoordinateSpace();
      if (displayW <= 0 || displayH <= 0 || sourceW <= 0 || sourceH <= 0) {
        const rx = 0.5;
        const ry = 0.5;
        return {
          x: clamp(Math.round(rx * targetW), 0, targetW - 1),
          y: clamp(Math.round(ry * targetH), 0, targetH - 1),
          rx,
          ry,
          srcW: sourceW,
          srcH: sourceH
        };
      }

      const fit =
        resolvedStreamFit === 'contain'
          ? getObjectContainRect(
              sourceW,
              sourceH,
              displayW,
              displayH,
              resolvedAlign
            )
          : getObjectCoverRect(
              sourceW,
              sourceH,
              displayW,
              displayH,
              resolvedAlign
            );
      const sourceX = clamp((displayX - fit.left) / fit.scale, 0, sourceW);
      const sourceY = clamp((displayY - fit.top) / fit.scale, 0, sourceH);
      const rx = clamp(sourceX / sourceW, 0, 1);
      const ry = clamp(sourceY / sourceH, 0, 1);
      const xDev = rx * targetW;
      const yDev = ry * targetH;
      return {
        x: clamp(Math.round(xDev), 0, targetW - 1),
        y: clamp(Math.round(yDev), 0, targetH - 1),
        rx,
        ry,
        srcW: sourceW,
        srcH: sourceH
      };
    },
    [getCoordinateSpace, resolvedAlign, resolvedStreamFit]
  );

  const highlightStyle = React.useMemo<React.CSSProperties | undefined>(() => {
    if (!highlightBounds || wrapSize.width <= 0 || wrapSize.height <= 0)
      return undefined;
    const { sourceW, sourceH, targetW, targetH } = getCoordinateSpace();
    const fit =
      resolvedStreamFit === 'contain'
        ? getObjectContainRect(
            sourceW,
            sourceH,
            wrapSize.width,
            wrapSize.height,
            resolvedAlign
          )
        : getObjectCoverRect(
            sourceW,
            sourceH,
            wrapSize.width,
            wrapSize.height,
            resolvedAlign
          );
    const [x1, y1, x2, y2] = highlightBounds;
    return {
      left: `${fit.left + (x1 / targetW) * fit.width}px`,
      top: `${fit.top + (y1 / targetH) * fit.height}px`,
      width: `${((x2 - x1) / targetW) * fit.width}px`,
      height: `${((y2 - y1) / targetH) * fit.height}px`
    };
  }, [
    getCoordinateSpace,
    highlightBounds,
    resolvedStreamFit,
    resolvedAlign,
    wrapSize.height,
    wrapSize.width
  ]);

  const streamObjectClass = React.useMemo(() => {
    const pos = resolvedAlign === 'bottom' ? 'bottom' : 'center';
    if (resolvedStreamFit === 'contain') {
      return pos === 'bottom'
        ? 'object-contain object-bottom'
        : 'object-contain object-center';
    }
    return pos === 'bottom'
      ? 'object-cover object-bottom'
      : 'object-cover object-center';
  }, [resolvedAlign, resolvedStreamFit]);
  const showWebRtcVideo =
    webrtcRequested && (webrtc.active || webrtc.connecting);
  const showH264Canvas =
    !showWebRtcVideo && (h264Active || (h264Only && hasFrame));

  // Grab the frame that is actually on screen. Three surfaces can be live
  // (WebRTC video, H264 canvas, MJPEG img) and only one is visible at a time,
  // so read whichever is currently showing.
  useEffect(() => {
    if (!captureFrameRef) return;
    captureFrameRef.current = () => {
      const draw = (
        source: CanvasImageSource,
        width: number,
        height: number
      ): string | null => {
        if (!width || !height) return null;
        const scratch = document.createElement('canvas');
        scratch.width = width;
        scratch.height = height;
        const ctx = scratch.getContext('2d');
        if (!ctx) return null;
        ctx.drawImage(source, 0, 0, width, height);
        try {
          return scratch.toDataURL('image/png');
        } catch {
          // Tainted canvas (cross-origin MJPEG). Nothing usable here.
          return null;
        }
      };

      if (showWebRtcVideo) {
        const video = videoRef.current;
        if (video?.videoWidth) {
          return draw(video, video.videoWidth, video.videoHeight);
        }
      }
      if (showH264Canvas) {
        const canvas = canvasRef.current;
        if (canvas?.width) {
          try {
            return canvas.toDataURL('image/png');
          } catch {
            return null;
          }
        }
      }
      const img = imageRef.current;
      if (img?.naturalWidth) {
        return draw(img, img.naturalWidth, img.naturalHeight);
      }
      return null;
    };
    return () => {
      captureFrameRef.current = null;
    };
  }, [captureFrameRef, showWebRtcVideo, showH264Canvas]);

  const requestStreamRefreshAfterInput = useCallback(() => {
    if (!h264SubscriptionAllowed) return;

    const requestIfStillNeeded = (frameVersionAtInput: number) => {
      const now = Date.now();
      if (
        !shouldRequestH264RefreshAfterInput({
          isActive: Boolean(isActive),
          h264DecodeAllowed,
          h264Only,
          hasFrame: hasFrameRef.current,
          frameAdvancedSinceInput:
            h264RenderedFrameVersionRef.current !== frameVersionAtInput,
          now,
          lastRequestAt: lastInputIdrRef.current
        })
      ) {
        return;
      }
      lastInputIdrRef.current = now;
      requestIdr(device.serial, H264_INPUT_REFRESH_MIN_INTERVAL_MS);
    };

    const frameVersionAtInput = h264RenderedFrameVersionRef.current;
    if (hasFrameRef.current && !h264Only) return;

    if (inputRefreshTimerRef.current) {
      clearTimeout(inputRefreshTimerRef.current);
    }
    inputRefreshTimerRef.current = setTimeout(() => {
      inputRefreshTimerRef.current = null;
      requestIfStillNeeded(frameVersionAtInput);
    }, H264_INPUT_REFRESH_WAIT_MS);
  }, [
    device.serial,
    h264DecodeAllowed,
    h264Only,
    h264SubscriptionAllowed,
    isActive
  ]);

  const bind = useGesture(
    {
      onDrag: (state) => {
        if (!state || state.first) return;
        const { last, xy, initial } = state;
        const elapsed =
          'elapsed' in state
            ? ((state as { elapsed?: number }).elapsed ?? 300)
            : 300;
        if (!xy || !initial) return;
        if (xy[0] !== initial[0] || xy[1] !== initial[1])
          draggedRef.current = true;
        if (!last) return;
        if (xy[0] !== initial[0] || xy[1] !== initial[1]) {
          const r = wrapRef.current?.getBoundingClientRect();
          if (!r) return;
          const p1 = clientToDevice(
            initial[0] - r.left,
            initial[1] - r.top,
            r.width,
            r.height
          );
          const p2 = clientToDevice(
            xy[0] - r.left,
            xy[1] - r.top,
            r.width,
            r.height
          );
          const rx1 = parseFloat((p1.rx ?? p1.x / dw).toFixed(4));
          const ry1 = parseFloat((p1.ry ?? p1.y / dh).toFixed(4));
          const rx2 = parseFloat((p2.rx ?? p2.x / dw).toFixed(4));
          const ry2 = parseFloat((p2.ry ?? p2.y / dh).toFixed(4));
          if (gestureMode === 'drag') {
            const ms = 1000;
            wsSend({
              type: 'drag',
              serial: device.serial,
              x1: p1.x,
              y1: p1.y,
              x2: p2.x,
              y2: p2.y,
              ms
            });
            requestStreamRefreshAfterInput();
            onDragGestureRef.current?.(rx1, ry1, rx2, ry2, ms);
          } else {
            const ms = Math.max(300, Math.min(elapsed, 1000));
            wsSend({
              type: 'swipe',
              serial: device.serial,
              x1: p1.x,
              y1: p1.y,
              x2: p2.x,
              y2: p2.y,
              ms
            });
            requestStreamRefreshAfterInput();
            onSwipeRef.current?.(rx1, ry1, rx2, ry2, ms);
          }
        }
      },
      onPinch: (state) => {
        if (!state.last) return;
        const r = wrapRef.current?.getBoundingClientRect();
        if (!r) return;
        const origin = state.origin as [number, number];
        const p = clientToDevice(
          origin[0] - r.left,
          origin[1] - r.top,
          r.width,
          r.height
        );
        const scale = (state as { offset?: [number, number] }).offset?.[0] ?? 1;
        wsSend({
          type: 'pinch',
          serial: device.serial,
          cx: p.x,
          cy: p.y,
          scale,
          ms: 400
        });
        requestStreamRefreshAfterInput();
      }
    },
    {
      drag: { threshold: 5, pointer: { touch: true } },
      pinch: { pointer: { touch: true } },
      eventOptions: { passive: false }
    }
  );

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (draggedRef.current) {
        draggedRef.current = false;
        return;
      }
      const el = wrapRef.current ?? e.currentTarget;
      const rect = el.getBoundingClientRect();
      const p = clientToDevice(
        e.clientX - rect.left,
        e.clientY - rect.top,
        rect.width,
        rect.height
      );

      if (gestureMode === 'double_tap') {
        if (!interactive) return;
        wsSend({ type: 'double_tap', serial: device.serial, x: p.x, y: p.y });
        requestStreamRefreshAfterInput();
        return;
      }
      // Recording (`onTap`): still perform tap + capture ratios even if tile mode is "swipe"
      const allowTap = mode === 'tap' || !!onTap;
      if (!allowTap) return;
      if (interactive) {
        wsSend({ type: 'tap', serial: device.serial, x: p.x, y: p.y });
        requestStreamRefreshAfterInput();
      }
      if (onTap) {
        onTap(p.rx, p.ry);
      }
    },
    [
      mode,
      gestureMode,
      interactive,
      clientToDevice,
      wsSend,
      device.serial,
      onTap,
      requestStreamRefreshAfterInput
    ]
  );

  const handleDoubleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (mode !== 'tap' || gestureMode === 'double_tap') return; // double_tap mode uses single click
      const el = wrapRef.current ?? e.currentTarget;
      const rect = el.getBoundingClientRect();
      const p = clientToDevice(
        e.clientX - rect.left,
        e.clientY - rect.top,
        rect.width,
        rect.height
      );
      wsSend({ type: 'double_tap', serial: device.serial, x: p.x, y: p.y });
      requestStreamRefreshAfterInput();
    },
    [
      mode,
      gestureMode,
      clientToDevice,
      wsSend,
      device.serial,
      requestStreamRefreshAfterInput
    ]
  );

  // ── Region select (tap_image crop) ────────────────────────────────────────
  // Kept in wrapper-relative pixels while dragging so the box tracks the cursor
  // exactly; converted to device ratios only once, on release.
  const regionActive = Boolean(regionSelect?.active);
  const [regionDrag, setRegionDrag] = useState<{
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  } | null>(null);
  const regionStartRef = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (!regionActive) setRegionDrag(null);
  }, [regionActive]);

  useEffect(() => {
    if (!regionActive) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') regionSelect?.onCancel();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [regionActive, regionSelect]);

  const regionPoint = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }, []);

  const handleRegionPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      e.currentTarget.setPointerCapture(e.pointerId);
      const p = regionPoint(e);
      regionStartRef.current = p;
      setRegionDrag({ x1: p.x, y1: p.y, x2: p.x, y2: p.y });
    },
    [regionPoint]
  );

  const handleRegionPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!regionStartRef.current) return;
      e.stopPropagation();
      const p = regionPoint(e);
      const start = regionStartRef.current;
      setRegionDrag({ x1: start.x, y1: start.y, x2: p.x, y2: p.y });
    },
    [regionPoint]
  );

  const handleRegionPointerUp = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const start = regionStartRef.current;
      if (!start) return;
      e.stopPropagation();
      regionStartRef.current = null;
      const el = e.currentTarget;
      const rect = el.getBoundingClientRect();
      const p = regionPoint(e);
      setRegionDrag(null);

      // A click with no drag is almost always a misunderstanding of the mode,
      // not a request to crop a 1px template. Leave the mode on so the hint
      // stays visible and the user can try again.
      if (Math.abs(p.x - start.x) < 8 || Math.abs(p.y - start.y) < 8) return;

      const a = clientToDevice(start.x, start.y, rect.width, rect.height);
      const b = clientToDevice(p.x, p.y, rect.width, rect.height);
      regionSelect?.onComplete({
        rx1: Math.min(a.rx, b.rx),
        ry1: Math.min(a.ry, b.ry),
        rx2: Math.max(a.rx, b.rx),
        ry2: Math.max(a.ry, b.ry)
      });
    },
    [clientToDevice, regionPoint, regionSelect]
  );

  const handleWheel = useCallback(
    (e: React.WheelEvent<HTMLDivElement>) => {
      if (!e.ctrlKey) return; // Ctrl+scroll = pinch
      e.preventDefault();
      const el = wrapRef.current ?? e.currentTarget;
      const rect = el.getBoundingClientRect();
      const p = clientToDevice(
        e.clientX - rect.left,
        e.clientY - rect.top,
        rect.width,
        rect.height
      );
      const scale = e.deltaY < 0 ? 2.0 : 0.5; // scroll up = zoom in, down = zoom out
      wsSend({
        type: 'pinch',
        serial: device.serial,
        cx: p.x,
        cy: p.y,
        scale,
        ms: 400
      });
      requestStreamRefreshAfterInput();
    },
    [clientToDevice, wsSend, device.serial, requestStreamRefreshAfterInput]
  );

  return (
    <div className='flex h-full min-h-0 w-full flex-col'>
      <div
        {...(interactive && !regionActive ? bind() : {})}
        ref={wrapRef}
        onClick={
          (interactive || onTap) && !regionActive ? handleClick : undefined
        }
        onDoubleClick={
          interactive && !regionActive ? handleDoubleClick : undefined
        }
        onWheel={interactive && !regionActive ? handleWheel : undefined}
        className={`relative min-h-0 w-full flex-1 overflow-hidden bg-black ${
          !interactive && !onTap
            ? 'cursor-default'
            : gestureMode === 'double_tap'
              ? 'cursor-cell'
              : gestureMode === 'drag'
                ? 'cursor-grab'
                : mode === 'swipe'
                  ? 'cursor-crosshair'
                  : 'cursor-pointer'
        } ${interactive ? 'touch-none' : ''}`}
        id={`wrap-${id}`}
      >
        {webrtcRequested && (
          <video
            key={`webrtc-${device.serial}`}
            ref={videoRef}
            muted
            playsInline
            autoPlay
            className={`pointer-events-none absolute inset-0 h-full w-full ${streamObjectClass} transition-opacity duration-300 ${showWebRtcVideo ? 'opacity-100' : 'opacity-0'}`}
          />
        )}

        {/* MJPEG baseline for auto transport — omitted on H264-only control surfaces. */}
        {mjpegUrl && !mjpegFailed && (
          // eslint-disable-next-line @next/next/no-img-element -- MJPEG stream endpoint must stay as a native img.
          <img
            key={`mjpeg-${device.serial}`}
            ref={imageRef}
            src={mjpegUrl}
            alt={`${device.brand} ${device.model}`}
            fetchPriority={streamFetchPriority}
            decoding='async'
            className={`absolute inset-0 h-full w-full ${streamObjectClass} transition-opacity duration-500 ${showH264Canvas || showWebRtcVideo ? 'pointer-events-none opacity-0' : 'opacity-100'}`}
            onLoad={() => {
              setHasFrame(true);
              const img = imageRef.current;
              if (img?.naturalWidth && img?.naturalHeight) {
                updateStreamSize(img.naturalWidth, img.naturalHeight);
              }
            }}
            onError={() => setMjpegFailed(true)}
            draggable={false}
          />
        )}
        {/* H264 live canvas — WebCodecs decode, zero MSE buffering latency */}
        <canvas
          key={`h264-${device.serial}-${h264RestartKey}`}
          ref={canvasRef}
          className={`pointer-events-none absolute inset-0 h-full w-full ${streamObjectClass} transition-opacity duration-500 ${showH264Canvas ? 'opacity-100' : 'opacity-0'}`}
        />

        {/* Solid placeholder — contentful paint before stream; avoids tiny text becoming LCP. */}
        {isActive && !hasFrame && (
          <div
            className='absolute inset-0 bg-gradient-to-b from-zinc-700 to-zinc-900'
            aria-hidden
          />
        )}

        {/* Highlight bounds overlay for XML tree node selection */}
        {highlightBounds && dw > 0 && dh > 0 && (
          <div
            className='pointer-events-none absolute border-2 border-red-500 bg-red-500/15 transition-all duration-150'
            style={highlightStyle}
          />
        )}

        {/* Frozen frame under the selection UI: the stream keeps running
            underneath, but the user drags on — and cuts from — this exact image. */}
        {regionActive && regionSelect?.frozenFrame && (
          // eslint-disable-next-line @next/next/no-img-element -- local data URL
          <img
            src={regionSelect.frozenFrame}
            alt=''
            draggable={false}
            className={`pointer-events-none absolute inset-0 z-20 h-full w-full ${streamObjectClass}`}
          />
        )}

        {/* Region select: sits above the stream so the drag never taps through */}
        {regionActive && (
          <div
            className='absolute inset-0 z-30 cursor-crosshair touch-none'
            onPointerDown={handleRegionPointerDown}
            onPointerMove={handleRegionPointerMove}
            onPointerUp={handleRegionPointerUp}
            onPointerCancel={handleRegionPointerUp}
          >
            <div className='pointer-events-none absolute inset-0 bg-black/35' />
            {regionDrag && (
              <div
                className='pointer-events-none absolute border-2 border-sky-400 bg-sky-400/10 shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]'
                style={{
                  left: Math.min(regionDrag.x1, regionDrag.x2),
                  top: Math.min(regionDrag.y1, regionDrag.y2),
                  width: Math.abs(regionDrag.x2 - regionDrag.x1),
                  height: Math.abs(regionDrag.y2 - regionDrag.y1)
                }}
              />
            )}
            <div className='pointer-events-none absolute inset-x-2 top-2 rounded-md bg-sky-950/85 px-2 py-1.5 text-center text-[10px] leading-snug text-sky-100'>
              {regionSelect?.hint ??
                'Kéo chọn vùng cần nhận diện trên màn hình. Nhấn Esc để huỷ.'}
            </div>
          </div>
        )}

        {/* Status badge: avoid "loading forever" when offline/unresponsive */}
        <div className='pointer-events-none absolute left-2 top-2 flex items-center gap-2'>
          {!isActive ? (
            <Badge
              variant='outline'
              className='border-red-500/30 bg-red-500/10 text-[10px] text-red-700 dark:text-red-300'
            >
              {t('badgeOffline')}
            </Badge>
          ) : isUnresponsive ? (
            <Badge
              variant='outline'
              className='border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-800 dark:text-amber-200'
            >
              {t('badgeUnresponsive')}
            </Badge>
          ) : null}
        </div>

        {!hasFrame && isActive && (
          <div
            className='absolute inset-0 flex items-center justify-center'
            style={{ pointerEvents: 'none' }}
            aria-live='polite'
          >
            <span className='sr-only'>
              {isUnresponsive
                ? t('streamUnresponsive')
                : wsConnected
                  ? t('streamWaitingFirstFrame')
                  : t('streamConnecting')}
              {loadingElapsedSec > 0 ? ` (${loadingElapsedSec}s)` : ''}
            </span>
            {!isUnresponsive && (
              <div className='h-5 w-5 animate-spin rounded-full border-2 border-zinc-400/80 border-t-transparent' />
            )}
          </div>
        )}
        {!isActive && (
          <div className='absolute inset-0 flex items-center justify-center text-xs text-muted-foreground'>
            {t('streamOffline')}
          </div>
        )}
      </div>
      {SHOW_RELAY_SCRCPY_UI_TOGGLE && isContinuous && (
        <div className='mt-1 flex shrink-0 items-center justify-between gap-2 text-[10px] text-muted-foreground'>
          <span className='truncate' title={t('screenStreamHint')}>
            {t('screenStream')}
          </span>
          <Switch
            checked={screenStreamOn}
            disabled={!isActive || streamToggleBusy}
            onCheckedChange={(c) => void onScreenStreamChange(c)}
            className='scale-90'
            aria-label={t('screenStream')}
          />
        </div>
      )}
      {!captionBelowFrame && (
        <div className='mt-1 flex shrink-0 justify-center px-1 text-[10px] text-muted-foreground'>
          <span
            className='truncate text-center font-mono'
            id={`app-${id}`}
            title={device.current_app ?? ''}
          >
            {(device.current_app ?? '—').split('.').slice(-1)[0] ?? '—'}
          </span>
        </div>
      )}
    </div>
  );
}
