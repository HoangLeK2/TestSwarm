'use client';

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useGesture } from '@use-gesture/react';
import type { Device } from '../types';
import { serialToId } from '../helpers';
import { deviceFarmBackendBase, farmApi } from '@/lib/farm-api';
import { Switch } from '@/components/ui/switch';
import { toast } from 'sonner';
import { tokenStorage } from '@/lib/token-storage';
import { useH264Video } from '../hooks/use-h264-canvas';
import { subscribeDeviceFarm } from '../services/ws';
import { useTranslations } from 'next-intl';
import { SHOW_RELAY_SCRCPY_UI_TOGGLE } from '../streaming-ui-flags';


interface DeviceScreenProps {
  device: Device;
  wsSend: (obj: object) => void;
  mode: 'tap' | 'swipe';
  onTap?: (rx: number, ry: number) => void;
  /** Normalized 0–1 coords + duration (ms), after a completed swipe drag (not drag mode). */
  onSwipe?: (rx1: number, ry1: number, rx2: number, ry2: number, durationMs: number) => void;
  /** Normalized 0–1 + duration when gesture mode is drag. */
  onDragGesture?: (rx1: number, ry1: number, rx2: number, ry2: number, durationMs: number) => void;
  apiBase?: string;
  /** Highlight bounds overlay [x1, y1, x2, y2] in device pixels */
  highlightBounds?: [number, number, number, number] | null;
  /** Gesture mode: tap, swipe, double_tap, drag */
  gestureMode?: 'tap' | 'swipe' | 'double_tap' | 'drag';
}

export function DeviceScreen({ device, wsSend, mode, onTap, onSwipe, onDragGesture, highlightBounds, gestureMode }: DeviceScreenProps) {
  const t = useTranslations('devicesFarm');
  const wrapRef    = useRef<HTMLDivElement>(null);
  const canvasRef  = useRef<HTMLCanvasElement>(null);
  const draggedRef = useRef(false);
  const dragStartRef = useRef<{ x: number; y: number } | null>(null);
  const onSwipeRef = useRef(onSwipe);
  const onDragGestureRef = useRef(onDragGesture);
  onSwipeRef.current = onSwipe;
  onDragGestureRef.current = onDragGesture;
  const [hasFrame, setHasFrame] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [loadingElapsedSec, setLoadingElapsedSec] = useState(0);

  const id = serialToId(device.serial);
  const dw = device.screen_width  || 1080;
  const dh = device.screen_height || 1920;

  const isActive =
    device.state && !['DISCONNECTED', 'DEAD'].includes(device.state.toUpperCase());

  // Track whether jmuxer has delivered at least one H264 frame
  const [h264Active, setH264Active] = useState(false);
  const h264TimeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const h264StableTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const [mjpegEnabled, setMjpegEnabled] = useState(true);

  const [streamingFlags, setStreamingFlags] = useState<{
    mode: string;
    autoAttach: boolean;
  } | null>(null);
  const [screenStreamOn, setScreenStreamOn] = useState(true);
  const [streamToggleBusy, setStreamToggleBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    farmApi
      .get<{ streaming_mode?: string; streaming_auto_attach_scrcpy?: boolean }>('/config')
      .then((res) => {
        if (cancelled) return;
        setStreamingFlags({
          mode: String(res.data?.streaming_mode ?? 'periodic'),
          autoAttach: Boolean(res.data?.streaming_auto_attach_scrcpy ?? true),
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

  /** Sync from server (default on). Matches grid tile when UI toggle is hidden. */
  useLayoutEffect(() => {
    if (!streamingFlags) return;
    if (streamingFlags.mode !== 'continuous') {
      setScreenStreamOn(true);
      return;
    }
    const serverWants =
      device.relay_scrcpy_enabled !== undefined && device.relay_scrcpy_enabled !== null
        ? Boolean(device.relay_scrcpy_enabled)
        : Boolean(streamingFlags.autoAttach ?? true);
    setScreenStreamOn(serverWants);
  }, [
    streamingFlags?.mode,
    streamingFlags?.autoAttach,
    device.serial,
    device.relay_scrcpy_enabled,
  ]);

  // Until /api/config returns, assume non-continuous (fail-open: keep legacy full stream).
  const isContinuous =
    streamingFlags !== null && streamingFlags.mode === 'continuous';
  /** Subscribe relay H.264 + honor server detach; MJPEG below stays on so you always see picture. */
  const relayH264Allowed =
    streamingFlags === null || !isContinuous || screenStreamOn;

  const onScreenStreamChange = useCallback(
    async (checked: boolean) => {
      if (!isContinuous || !isActive) return;
      setStreamToggleBusy(true);
      try {
        if (checked) {
          await farmApi.post(`/devices/${encodeURIComponent(device.serial)}/scrcpy/attach`, {});
        } else {
          await farmApi.post(`/devices/${encodeURIComponent(device.serial)}/scrcpy/detach`, {});
        }
        setScreenStreamOn(checked);
        if (!checked) {
          setHasFrame(false);
          setH264Active(false);
          setMjpegEnabled(false);
        } else {
          setMjpegEnabled(true);
        }
      } catch (err) {
        const msg = err && typeof err === 'object' && 'response' in err
          ? String((err as { response?: { data?: { error?: string } } }).response?.data?.error ?? '')
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

  // Always show MJPEG as baseline — it's hidden (opacity-0) once H264 starts playing
  const mjpegUrl = React.useMemo(() => {
    if (!isActive || !mjpegEnabled) return null;
    const base = `${deviceFarmBackendBase}/stream/${encodeURIComponent(device.serial)}?fps=30`;
    const token = tokenStorage.getAuthToken();
    return token ? `${base}&token=${encodeURIComponent(token)}` : base;
  }, [isActive, mjpegEnabled, device.serial]);

  // Always pass real serial so binary frames are subscribed immediately on mount.
  // jmuxer gracefully handles missing MSE via onError — MJPEG fallback stays visible.
  useH264Video(
    isActive && relayH264Allowed ? device.serial : '',
    canvasRef,
    {
      onFrame: useCallback(() => {
        if (!hasFrame) setHasFrame(true);
        if (!h264Active) setH264Active(true);
        if (h264TimeoutRef.current) clearTimeout(h264TimeoutRef.current);
        h264TimeoutRef.current = setTimeout(() => setH264Active(false), 8000);
      }, [hasFrame, h264Active]),
    }
  );

  // Reset h264Active when device changes or goes offline
  useEffect(() => {
    setH264Active(false);
    setMjpegEnabled(true);
    if (h264TimeoutRef.current) clearTimeout(h264TimeoutRef.current);
    if (h264StableTimerRef.current) clearTimeout(h264StableTimerRef.current);
  }, [device.serial, isActive, relayH264Allowed]);

  // Once H264 stays healthy for a while, stop MJPEG network fetches entirely.
  // If H264 drops, MJPEG is re-enabled immediately as fallback.
  useEffect(() => {
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
      }, 5000);
    } else {
      if (h264StableTimerRef.current) clearTimeout(h264StableTimerRef.current);
      setMjpegEnabled(true);
    }
    return () => {
      if (h264StableTimerRef.current) clearTimeout(h264StableTimerRef.current);
    };
  }, [isActive, h264Active, relayH264Allowed]);

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

  // ── Touch / gesture ──────────────────────────────────────────────────────
  const clientToDevice = useCallback(
    (displayX: number, displayY: number, displayW: number, displayH: number) => {
      if (displayW <= 0 || displayH <= 0 || dw <= 0 || dh <= 0) return { x: 0, y: 0 };
      return {
        x: Math.max(0, Math.min(Math.round((displayX / displayW) * dw), dw - 1)),
        y: Math.max(0, Math.min(Math.round((displayY / displayH) * dh), dh - 1)),
      };
    },
    [dw, dh]
  );

  const bind = useGesture(
    {
      onDrag: (state) => {
        if (!state || state.first) return;
        const { last, xy, initial } = state;
        const elapsed = 'elapsed' in state ? (state as { elapsed?: number }).elapsed ?? 300 : 300;
        if (!xy || !initial) return;
        if (xy[0] !== initial[0] || xy[1] !== initial[1]) draggedRef.current = true;
        if (!last) return;
        if (xy[0] !== initial[0] || xy[1] !== initial[1]) {
          const r = wrapRef.current?.getBoundingClientRect();
          if (!r) return;
          const p1 = clientToDevice(initial[0] - r.left, initial[1] - r.top, r.width, r.height);
          const p2 = clientToDevice(xy[0] - r.left, xy[1] - r.top, r.width, r.height);
          const rx1 = parseFloat((p1.x / dw).toFixed(4));
          const ry1 = parseFloat((p1.y / dh).toFixed(4));
          const rx2 = parseFloat((p2.x / dw).toFixed(4));
          const ry2 = parseFloat((p2.y / dh).toFixed(4));
          if (gestureMode === 'drag') {
            const ms = 1000;
            wsSend({ type: 'drag', serial: device.serial, x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y, ms });
            onDragGestureRef.current?.(rx1, ry1, rx2, ry2, ms);
          } else {
            const ms = Math.max(300, Math.min(elapsed, 1000));
            wsSend({ type: 'swipe', serial: device.serial, x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y, ms });
            onSwipeRef.current?.(rx1, ry1, rx2, ry2, ms);
          }
        }
      },
      onPinch: (state) => {
        if (!state.last) return;
        const r = wrapRef.current?.getBoundingClientRect();
        if (!r) return;
        const origin = state.origin as [number, number];
        const p = clientToDevice(origin[0] - r.left, origin[1] - r.top, r.width, r.height);
        const scale = (state as { offset?: [number, number] }).offset?.[0] ?? 1;
        wsSend({ type: 'pinch', serial: device.serial, cx: p.x, cy: p.y, scale, ms: 400 });
      },
    },
    { drag: { threshold: 5 }, pointer: { touch: true }, event: { passive: false } }
  );

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (draggedRef.current) { draggedRef.current = false; return; }
      const el   = (e.target as HTMLElement) ?? e.currentTarget;
      const rect = el.getBoundingClientRect();
      const p    = clientToDevice(e.clientX - rect.left, e.clientY - rect.top, rect.width, rect.height);

      if (gestureMode === 'double_tap') {
        wsSend({ type: 'double_tap', serial: device.serial, x: p.x, y: p.y });
        return;
      }
      // Recording (`onTap`): still perform tap + capture ratios even if tile mode is "swipe"
      const allowTap = mode === 'tap' || !!onTap;
      if (!allowTap) return;
      wsSend({ type: 'tap', serial: device.serial, x: p.x, y: p.y });
      if (onTap && rect.width > 0 && rect.height > 0) {
        onTap((e.clientX - rect.left) / rect.width, (e.clientY - rect.top) / rect.height);
      }
    },
    [mode, gestureMode, clientToDevice, wsSend, device.serial, onTap]
  );

  const handleDoubleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (mode !== 'tap' || gestureMode === 'double_tap') return; // double_tap mode uses single click
      const el   = (e.target as HTMLElement) ?? e.currentTarget;
      const rect = el.getBoundingClientRect();
      const p    = clientToDevice(e.clientX - rect.left, e.clientY - rect.top, rect.width, rect.height);
      wsSend({ type: 'double_tap', serial: device.serial, x: p.x, y: p.y });
    },
    [mode, gestureMode, clientToDevice, wsSend, device.serial]
  );

  const handleWheel = useCallback(
    (e: React.WheelEvent<HTMLDivElement>) => {
      if (!e.ctrlKey) return; // Ctrl+scroll = pinch
      e.preventDefault();
      const el   = (e.target as HTMLElement) ?? e.currentTarget;
      const rect = el.getBoundingClientRect();
      const p    = clientToDevice(e.clientX - rect.left, e.clientY - rect.top, rect.width, rect.height);
      const scale = e.deltaY < 0 ? 2.0 : 0.5; // scroll up = zoom in, down = zoom out
      wsSend({ type: 'pinch', serial: device.serial, cx: p.x, cy: p.y, scale, ms: 400 });
    },
    [clientToDevice, wsSend, device.serial]
  );

  return (
    <>
      <div
        {...bind()}
        ref={wrapRef}
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
        onWheel={handleWheel}
        className={`relative w-full overflow-hidden rounded-md border border-border bg-black ${
          gestureMode === 'double_tap' ? 'cursor-cell' :
          gestureMode === 'drag' ? 'cursor-grab' :
          mode === 'swipe' ? 'cursor-crosshair' : 'cursor-pointer'
        }`}
        style={{ aspectRatio: `${dw}/${dh}` }}
        id={`wrap-${id}`}
      >
        {/* MJPEG baseline — always shown until H264 takes over */}
        {mjpegUrl && (
          <img
            src={mjpegUrl}
            alt={`${device.brand} ${device.model}`}
            className={`absolute inset-0 h-full w-full object-contain transition-opacity duration-500 ${h264Active ? 'opacity-0 pointer-events-none' : 'opacity-100'}`}
            onLoad={() => { setHasFrame(true); }}
            draggable={false}
          />
        )}
        {/* H264 live canvas — WebCodecs decode, zero MSE buffering latency */}
        <canvas
          ref={canvasRef}
          className={`pointer-events-none absolute inset-0 h-full w-full object-contain transition-opacity duration-500 ${h264Active ? 'opacity-100' : 'opacity-0'}`}
        />

        {/* Highlight bounds overlay for XML tree node selection */}
        {highlightBounds && dw > 0 && dh > 0 && (
          <div
            className='pointer-events-none absolute border-2 border-red-500 bg-red-500/15 transition-all duration-150'
            style={{
              left:   `${(highlightBounds[0] / dw) * 100}%`,
              top:    `${(highlightBounds[1] / dh) * 100}%`,
              width:  `${((highlightBounds[2] - highlightBounds[0]) / dw) * 100}%`,
              height: `${((highlightBounds[3] - highlightBounds[1]) / dh) * 100}%`,
            }}
          />
        )}
        {!hasFrame && isActive && (
          <div
            className='absolute inset-0 flex items-center justify-center text-xs text-muted-foreground'
            style={{ pointerEvents: 'none' }}
          >
            <div className='flex flex-col items-center gap-2 rounded-md bg-black/40 px-3 py-2 backdrop-blur-[1px]'>
              <div className='h-4 w-4 animate-spin rounded-full border-2 border-zinc-400 border-t-transparent' />
              <div className='text-[11px] text-zinc-200'>
                {wsConnected ? t('streamWaitingFirstFrame') : t('streamConnecting')}
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
        <div className='mt-1 flex items-center justify-between gap-2 text-[10px] text-muted-foreground'>
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
      <div className='mt-1 flex items-center justify-between text-[10px] text-muted-foreground'>
        <span
          className={`font-medium ${device.battery >= 0 && device.battery < 20 ? 'text-red-500' : ''}`}
          id={`bat-${id}`}
        >
          🔋 {device.battery >= 0 ? `${device.battery}%` : '?'}
        </span>
        <span className='truncate font-mono' id={`app-${id}`} title={device.current_app ?? ''}>
          {(device.current_app ?? '—').split('.').slice(-1)[0] ?? '—'}
        </span>
        <span className='rounded bg-muted px-1 py-0.5 font-mono text-[9px]' id={`task-${id}`}>
          IDLE
        </span>
      </div>
    </>
  );
}
