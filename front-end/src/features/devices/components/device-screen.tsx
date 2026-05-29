'use client';

import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState
} from 'react';
import { useGesture } from '@use-gesture/react';
import type { Device } from '../types';
import { serialToId } from '../helpers';
import { deviceFarmBackendBase, farmApi } from '@/lib/farm-api';
import { Switch } from '@/components/ui/switch';
import { toast } from 'sonner';
import { tokenStorage } from '@/lib/token-storage';
import { useH264Video } from '../hooks/use-h264-canvas';
import {
  ensureWatchSerial,
  reconnectDeviceFarmSocket,
  requestIdr,
  subscribeDeviceFarm
} from '../services/ws';
import { useTranslations } from 'next-intl';
import { SHOW_RELAY_SCRCPY_UI_TOGGLE } from '../streaming-ui-flags';
import { Badge } from '@/components/ui/badge';

type Size = { width: number; height: number };

type ObjectFitRect = {
  left: number;
  top: number;
  width: number;
  height: number;
  scale: number;
};

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(value, max));
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
  /** Read-only preview: disable all interactions with device. */
  interactive?: boolean;
}

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
  interactive = true
}: DeviceScreenProps) {
  const t = useTranslations('devicesFarm');
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const draggedRef = useRef(false);
  const dragStartRef = useRef<{ x: number; y: number } | null>(null);
  const onSwipeRef = useRef(onSwipe);
  const onDragGestureRef = useRef(onDragGesture);
  onSwipeRef.current = onSwipe;
  onDragGestureRef.current = onDragGesture;
  const [hasFrame, setHasFrame] = useState(false);
  const [mjpegFailed, setMjpegFailed] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
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
  const [mjpegEnabled, setMjpegEnabled] = useState(true);
  const [h264Stalled, setH264Stalled] = useState(false);
  const [h264RestartKey, setH264RestartKey] = useState(0);
  const lastInputIdrRef = useRef(0);

  const [streamingFlags, setStreamingFlags] = useState<{
    mode: string;
    autoAttach: boolean;
  } | null>(null);
  const [screenStreamOn, setScreenStreamOn] = useState(true);
  const [streamToggleBusy, setStreamToggleBusy] = useState(false);
  const streamingMode = streamingFlags?.mode;
  const streamingAutoAttach = streamingFlags?.autoAttach;

  const updateStreamSize = useCallback((width: number, height: number) => {
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
  }, []);

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
    farmApi
      .get<{ streaming_mode?: string; streaming_auto_attach_scrcpy?: boolean }>(
        '/config'
      )
      .then((res) => {
        if (cancelled) return;
        setStreamingFlags({
          mode: String(res.data?.streaming_mode ?? 'periodic'),
          autoAttach: Boolean(res.data?.streaming_auto_attach_scrcpy ?? true)
        });
      })
      .catch(() => {
        if (cancelled) return;
        setStreamingFlags({ mode: 'periodic', autoAttach: true });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /** Sync from server (default on). Control page always streams when relay toggle is hidden. */
  useLayoutEffect(() => {
    if (!streamingMode) return;
    if (streamingMode !== 'continuous') {
      setScreenStreamOn(true);
      return;
    }
    if (!SHOW_RELAY_SCRCPY_UI_TOGGLE) {
      setScreenStreamOn(true);
      return;
    }
    const serverWants =
      device.relay_scrcpy_enabled !== undefined &&
      device.relay_scrcpy_enabled !== null
        ? Boolean(device.relay_scrcpy_enabled)
        : Boolean(streamingAutoAttach ?? true);
    setScreenStreamOn(serverWants);
  }, [
    streamingMode,
    streamingAutoAttach,
    device.serial,
    device.relay_scrcpy_enabled
  ]);

  // Until /api/config returns, assume non-continuous (fail-open: keep legacy full stream).
  const isContinuous =
    streamingFlags !== null && streamingMode === 'continuous';
  /** Subscribe relay H.264 + honor server detach; MJPEG below stays on so you always see picture. */
  const relayH264Allowed =
    streamingFlags === null || !isContinuous || screenStreamOn;
  const h264PrimaryMode = isContinuous && relayH264Allowed;

  // Viewer-gated streaming: when the server no longer auto-attaches scrcpy, the
  // device screen should attach on mount and detach on unmount.
  useEffect(() => {
    if (!isContinuous || !isActive) return;
    if (streamingAutoAttach !== false) return;
    if (!screenStreamOn) return;

    let detachScheduled = false;
    const serial = device.serial;

    ensureWatchSerial(serial);
    farmApi
      .post(`/devices/${encodeURIComponent(serial)}/scrcpy/attach`, {})
      .then(() => {
        ensureWatchSerial(serial);
        requestIdr(serial);
      })
      .catch(() => {});

    const onPageHide = () => {
      if (detachScheduled) return;
      detachScheduled = true;
      farmApi
        .post(`/devices/${encodeURIComponent(serial)}/scrcpy/detach`, {})
        .catch(() => {});
    };

    window.addEventListener('pagehide', onPageHide);
    return () => {
      window.removeEventListener('pagehide', onPageHide);
      // Do not detach on React effect re-runs (config load, screenStreamOn sync).
      // Server auto-stops after idle; pagehide handles tab close / navigation.
    };
  }, [
    device.serial,
    isActive,
    isContinuous,
    screenStreamOn,
    streamingAutoAttach
  ]);

  const onScreenStreamChange = useCallback(
    async (checked: boolean) => {
      if (!isContinuous || !isActive) return;
      setStreamToggleBusy(true);
      try {
        if (checked) {
          await farmApi.post(
            `/devices/${encodeURIComponent(device.serial)}/scrcpy/attach`,
            {}
          );
        } else {
          await farmApi.post(
            `/devices/${encodeURIComponent(device.serial)}/scrcpy/detach`,
            {}
          );
        }
        setScreenStreamOn(checked);
        if (!checked) {
          setHasFrame(false);
          setH264Active(false);
          setH264Stalled(false);
          setH264RestartKey((key) => key + 1);
          setMjpegEnabled(false);
        } else {
          setH264Stalled(false);
          setH264RestartKey((key) => key + 1);
          setMjpegEnabled(true);
        }
      } catch (err) {
        const msg =
          err && typeof err === 'object' && 'response' in err
            ? String(
                (err as { response?: { data?: { error?: string } } }).response
                  ?.data?.error ?? ''
              )
            : '';
        toast.error(
          checked ? t('screenStreamAttachError') : t('screenStreamDetachError'),
          { description: msg || undefined }
        );
      } finally {
        setStreamToggleBusy(false);
      }
    },
    [device.serial, isActive, isContinuous, t]
  );

  // In continuous mode, keep MJPEG visible until H264 is actually rendering.
  // Otherwise the canvas can be black during decoder warm-up or IDR recovery.
  const mjpegUrl = React.useMemo(() => {
    if (!isActive || !mjpegEnabled) return null;
    if (h264PrimaryMode && h264Active && !h264Stalled) return null;
    const fps = h264PrimaryMode ? 5 : 30;
    const base = `${deviceFarmBackendBase}/stream/${encodeURIComponent(device.serial)}?fps=${fps}`;
    const token = tokenStorage.getAuthToken();
    return token ? `${base}&token=${encodeURIComponent(token)}` : base;
  }, [
    isActive,
    mjpegEnabled,
    device.serial,
    h264PrimaryMode,
    h264Active,
    h264Stalled
  ]);

  useEffect(() => {
    setMjpegFailed(false);
  }, [mjpegUrl]);

  // Always pass real serial so binary frames are subscribed immediately on mount.
  // jmuxer gracefully handles missing MSE via onError — MJPEG fallback stays visible.
  useH264Video(isActive && relayH264Allowed ? device.serial : '', canvasRef, {
    restartKey: h264RestartKey,
    onFrame: useCallback(
      (frame?: { mostlyBlack: boolean }) => {
        const canvas = canvasRef.current;
        if (canvas?.width && canvas?.height) {
          updateStreamSize(canvas.width, canvas.height);
        }
        if (h264StallFallbackTimerRef.current) {
          clearTimeout(h264StallFallbackTimerRef.current);
          h264StallFallbackTimerRef.current = null;
        }
        if (frame?.mostlyBlack) {
          setH264Active(false);
          setH264Stalled(true);
          h264WarmupRef.current = { startedAt: 0, frames: 0 };
          return;
        }
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
          h264TimeoutRef.current = setTimeout(() => setH264Active(false), 8000);
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
          setMjpegEnabled(true);
          if (h264StallFallbackTimerRef.current) {
            clearTimeout(h264StallFallbackTimerRef.current);
          }
          h264StallFallbackTimerRef.current = setTimeout(() => {
            setH264Active(false);
            setHasFrame(false);
          }, 3000);
          if (burst.count >= 3) {
            burst.firstAt = now;
            burst.count = 0;
            reconnectDeviceFarmSocket('repeated_h264_stall');
          }
          return;
        }
        setH264Active(false);
        setH264Stalled(true);
        h264WarmupRef.current = { startedAt: 0, frames: 0 };
        setH264RestartKey((key) => key + 1);
        setHasFrame(false);
        setMjpegEnabled(true);
        if (burst.count >= 3) {
          burst.firstAt = now;
          burst.count = 0;
          reconnectDeviceFarmSocket('repeated_h264_stall');
        }
      },
      [hasFrame]
    )
  });

  // Reset h264Active when device changes or goes offline
  useEffect(() => {
    setH264Active(false);
    setH264Stalled(false);
    h264RecoveryBurstRef.current = { firstAt: 0, count: 0 };
    setH264RestartKey((key) => key + 1);
    setMjpegEnabled(true);
    h264WarmupRef.current = { startedAt: 0, frames: 0 };
    if (h264TimeoutRef.current) clearTimeout(h264TimeoutRef.current);
    if (h264StableTimerRef.current) clearTimeout(h264StableTimerRef.current);
    if (h264StallFallbackTimerRef.current)
      clearTimeout(h264StallFallbackTimerRef.current);
  }, [device.serial, isActive, relayH264Allowed]);

  // Once H264 is rendering, stop MJPEG network fetches entirely. Until then,
  // MJPEG remains the visible baseline so the user does not see a black canvas.
  useEffect(() => {
    if (h264PrimaryMode) {
      setMjpegEnabled(!h264Active || h264Stalled);
      return;
    }
    if (!isActive) {
      setMjpegEnabled(false);
      return;
    }
    if (!relayH264Allowed) {
      if (h264StableTimerRef.current) clearTimeout(h264StableTimerRef.current);
      setMjpegEnabled(true);
      return;
    }
    if (h264Active) {
      if (h264StableTimerRef.current) clearTimeout(h264StableTimerRef.current);
      h264StableTimerRef.current = setTimeout(() => {
        setMjpegEnabled(false);
      }, 2000);
    } else {
      if (h264StableTimerRef.current) clearTimeout(h264StableTimerRef.current);
      setMjpegEnabled(true);
    }
    return () => {
      if (h264StableTimerRef.current) clearTimeout(h264StableTimerRef.current);
    };
  }, [isActive, h264Active, relayH264Allowed, h264PrimaryMode, h264Stalled]);

  // Track shared WS connectivity so loading UI can distinguish
  // "socket not up yet" vs "stream waiting first frame".
  useEffect(() => {
    const unsub = subscribeDeviceFarm((msg) => {
      if (msg.type === 'ws_status') setWsConnected(Boolean(msg.connected));
    });
    return () => unsub();
  }, []);

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

  // H264-primary: if relay sends HEVC or scrcpy is flapping, MJPEG is the fallback picture.
  // Request IDR once after WS is up; re-arm MJPEG if still black after a few seconds.
  useEffect(() => {
    if (!isActive || !h264PrimaryMode || hasFrame) return;
    const armMjpeg = setTimeout(() => {
      setMjpegEnabled(true);
      setMjpegFailed(false);
    }, 2500);
    const idr = setTimeout(() => {
      if (wsConnected) requestIdr(device.serial);
    }, 1500);
    return () => {
      clearTimeout(armMjpeg);
      clearTimeout(idr);
    };
  }, [isActive, h264PrimaryMode, hasFrame, device.serial, wsConnected]);

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

  /** Mirror CSS object-cover exactly, then convert stream ratio to device pixels. */
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

      const fit = getObjectCoverRect(
        sourceW,
        sourceH,
        displayW,
        displayH,
        streamCoverAlign
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
    [getCoordinateSpace, streamCoverAlign]
  );

  const highlightStyle = React.useMemo<React.CSSProperties | undefined>(() => {
    if (!highlightBounds || wrapSize.width <= 0 || wrapSize.height <= 0)
      return undefined;
    const { sourceW, sourceH, targetW, targetH } = getCoordinateSpace();
    const fit = getObjectCoverRect(
      sourceW,
      sourceH,
      wrapSize.width,
      wrapSize.height,
      streamCoverAlign
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
    streamCoverAlign,
    wrapSize.height,
    wrapSize.width
  ]);

  const streamObjectClass =
    streamCoverAlign === 'bottom'
      ? 'object-cover object-bottom'
      : 'object-cover object-center';

  const requestStreamRefreshAfterInput = useCallback(() => {
    if (!isActive || !relayH264Allowed) return;
    const now = Date.now();
    if (now - lastInputIdrRef.current < 900) return;
    lastInputIdrRef.current = now;
    requestIdr(device.serial, 0);
  }, [device.serial, isActive, relayH264Allowed]);

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
      drag: { threshold: 5 },
      pointer: { touch: true },
      event: { passive: false }
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
        wsSend({ type: 'double_tap', serial: device.serial, x: p.x, y: p.y });
        requestStreamRefreshAfterInput();
        return;
      }
      // Recording (`onTap`): still perform tap + capture ratios even if tile mode is "swipe"
      const allowTap = mode === 'tap' || !!onTap;
      if (!allowTap) return;
      wsSend({ type: 'tap', serial: device.serial, x: p.x, y: p.y });
      requestStreamRefreshAfterInput();
      if (onTap) {
        onTap(p.rx, p.ry);
      }
    },
    [
      mode,
      gestureMode,
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
        {...(interactive ? bind() : {})}
        ref={wrapRef}
        onClick={interactive ? handleClick : undefined}
        onDoubleClick={interactive ? handleDoubleClick : undefined}
        onWheel={interactive ? handleWheel : undefined}
        className={`relative min-h-0 w-full flex-1 overflow-hidden bg-black ${
          !interactive
            ? 'cursor-default'
            : gestureMode === 'double_tap'
              ? 'cursor-cell'
              : gestureMode === 'drag'
                ? 'cursor-grab'
                : mode === 'swipe'
                  ? 'cursor-crosshair'
                  : 'cursor-pointer'
        }`}
        id={`wrap-${id}`}
      >
        {/* MJPEG baseline — always shown until H264 takes over */}
        {mjpegUrl && !mjpegFailed && (
          // eslint-disable-next-line @next/next/no-img-element -- MJPEG stream endpoint must stay as a native img.
          <img
            ref={imageRef}
            src={mjpegUrl}
            alt={`${device.brand} ${device.model}`}
            className={`absolute inset-0 h-full w-full ${streamObjectClass} transition-opacity duration-500 ${h264Active ? 'pointer-events-none opacity-0' : 'opacity-100'}`}
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
          className={`pointer-events-none absolute inset-0 h-full w-full ${streamObjectClass} transition-opacity duration-500 ${h264Active ? 'opacity-100' : 'opacity-0'}`}
        />

        {/* Highlight bounds overlay for XML tree node selection */}
        {highlightBounds && dw > 0 && dh > 0 && (
          <div
            className='pointer-events-none absolute border-2 border-red-500 bg-red-500/15 transition-all duration-150'
            style={highlightStyle}
          />
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
            className='absolute inset-0 flex items-center justify-center text-xs text-muted-foreground'
            style={{ pointerEvents: 'none' }}
          >
            <div className='flex flex-col items-center gap-2 rounded-md bg-black/40 px-3 py-2 backdrop-blur-[1px]'>
              {!isUnresponsive && (
                <div className='h-4 w-4 animate-spin rounded-full border-2 border-zinc-400 border-t-transparent' />
              )}
              <div className='text-[11px] text-zinc-200'>
                {isUnresponsive
                  ? t('streamUnresponsive')
                  : wsConnected
                    ? t('streamWaitingFirstFrame')
                    : t('streamConnecting')}
              </div>
              <div className='text-[10px] text-zinc-400'>
                {loadingElapsedSec}s
              </div>
            </div>
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
