'use client';

import React, { useCallback, useRef, useState } from 'react';
import { useGesture } from '@use-gesture/react';
import type { Device } from '../types';
import { serialToId } from '../helpers';
import { deviceFarmBackendBase } from '@/lib/farm-api';
import { tokenStorage } from '@/lib/token-storage';

interface DeviceScreenProps {
  device: Device;
  wsSend: (obj: object) => void;
  mode: 'tap' | 'swipe';
  onTap?: (rx: number, ry: number) => void;
  apiBase?: string;
  /** Highlight bounds overlay [x1, y1, x2, y2] in device pixels */
  highlightBounds?: [number, number, number, number] | null;
  /** Gesture mode: tap, swipe, double_tap, drag */
  gestureMode?: 'tap' | 'swipe' | 'double_tap' | 'drag';
}

export function DeviceScreen({ device, wsSend, mode, onTap, highlightBounds, gestureMode }: DeviceScreenProps) {
  const wrapRef    = useRef<HTMLDivElement>(null);
  const draggedRef = useRef(false);
  const dragStartRef = useRef<{ x: number; y: number } | null>(null);
  const [hasFrame, setHasFrame] = useState(false);

  const id = serialToId(device.serial);
  const dw = device.screen_width  || 1080;
  const dh = device.screen_height || 1920;

  const isActive =
    device.state && !['DISCONNECTED', 'DEAD'].includes(device.state.toUpperCase());

  const mjpegUrl = React.useMemo(() => {
    if (!isActive) return null;
    const base = `${deviceFarmBackendBase}/stream/${encodeURIComponent(device.serial)}?fps=30`;
    const token = tokenStorage.getAuthToken();
    return token ? `${base}&token=${encodeURIComponent(token)}` : base;
  }, [isActive, device.serial]);

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
          if (gestureMode === 'drag') {
            wsSend({ type: 'drag', serial: device.serial, x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y, ms: 1000 });
          } else {
            const ms = Math.max(300, Math.min(elapsed, 1000));
            wsSend({ type: 'swipe', serial: device.serial, x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y, ms });
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
      if (mode !== 'tap') return;
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
        {mjpegUrl ? (
          <img
            src={mjpegUrl}
            alt={`${device.brand} ${device.model}`}
            className='absolute inset-0 h-full w-full object-contain'
            onLoad={() => setHasFrame(true)}
            draggable={false}
          />
        ) : null}

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
            Loading...
          </div>
        )}
        {!isActive && (
          <div className='absolute inset-0 flex items-center justify-center text-xs text-muted-foreground'>
            Offline
          </div>
        )}
        <div className='pointer-events-none absolute right-1 top-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-mono text-white'>
          5 FPS
        </div>
      </div>
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
