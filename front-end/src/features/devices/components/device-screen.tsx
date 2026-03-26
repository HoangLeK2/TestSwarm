'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useGesture } from '@use-gesture/react';
import type { Device } from '../types';
import { serialToId } from '../helpers';
import { FrameDispatcher } from '../services/frame-dispatcher';
import type { FrameEvent, H264ConfigFrame, H264VideoFrame } from '../services/frame-dispatcher';

interface DeviceScreenProps {
  device: Device;
  wsSend: (obj: object) => void;
  mode: 'tap' | 'swipe';
  onTap?: (rx: number, ry: number) => void;
}

// ─── H264 WebCodecs decoder ──────────────────────────────────────────────────

const WEBCODECS_SUPPORTED = typeof window !== 'undefined' && 'VideoDecoder' in window;

class H264CanvasDecoder {
  private dec: VideoDecoder | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private ctx: CanvasRenderingContext2D | null = null;  // cached — avoid getContext per-frame
  private configData: Uint8Array | null = null;
  private onFirstFrame?: () => void;

  attach(canvas: HTMLCanvasElement, onFirstFrame: () => void) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.onFirstFrame = onFirstFrame;
  }

  detach() {
    this.close();
    this.canvas = null;
    this.ctx = null;
  }

  handleConfig(evt: H264ConfigFrame) {
    this.configData = evt.data;
    this._initDecoder(evt.width, evt.height);
  }

  handleFrame(evt: H264VideoFrame) {
    if (!this.dec || this.dec.state !== 'configured') {
      // Can't decode without a configured decoder — drop until next key frame
      return;
    }
    try {
      this.dec.decode(new EncodedVideoChunk({
        type:      evt.type === 'h264_key' ? 'key' : 'delta',
        timestamp: evt.ptsUs,
        data:      evt.data,
      }));
    } catch {
      // Decoder error — reset and wait for next key frame
      this.close();
    }
  }

  close() {
    try { this.dec?.close(); } catch {}
    this.dec = null;
  }

  private _initDecoder(w: number, h: number) {
    this.close();
    if (!WEBCODECS_SUPPORTED) return;
    const canvas = this.canvas;
    if (!canvas) return;

    const onFirstFrame = this.onFirstFrame;
    let firstFrameSent = false;

    const ctx = this.ctx;
    this.dec = new VideoDecoder({
      output: (frame) => {
        if (ctx) ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
        frame.close();
        if (!firstFrameSent) { firstFrameSent = true; onFirstFrame?.(); }
      },
      error: () => { this.dec = null; }, // reset on decode error; next key frame will reinit
    });

    try {
      // Build codec string from AVCDecoderConfigurationRecord if available:
      //   byte[1]=profile, byte[2]=constraints, byte[3]=level
      let codecStr = 'avc1.42E01E'; // H264 Baseline Level 3.0 fallback
      if (this.configData && this.configData.byteLength >= 4) {
        const p = this.configData[1].toString(16).padStart(2, '0');
        const c = this.configData[2].toString(16).padStart(2, '0');
        const l = this.configData[3].toString(16).padStart(2, '0');
        codecStr = `avc1.${p}${c}${l}`;
      }

      this.dec.configure({
        codec:       codecStr,
        codedWidth:  w,
        codedHeight: h,
        description: this.configData ?? undefined,
      });
    } catch {
      this.close();
    }
  }
}

// ─── Component ───────────────────────────────────────────────────────────────

export function DeviceScreen({ device, wsSend, mode, onTap }: DeviceScreenProps) {
  const wrapRef    = useRef<HTMLDivElement>(null);
  const canvasRef  = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const fpsRef     = useRef<HTMLDivElement>(null);
  const fpsTimesRef    = useRef<number[]>([]);
  const draggedRef     = useRef(false);
  const h264DecoderRef = useRef<H264CanvasDecoder | null>(null);
  // JPEG "latest-only" decode state — prevents concurrent createImageBitmap calls
  // and ensures we always render the most recent frame, not stale queued ones.
  const pendingJpegRef = useRef<{ data: Uint8Array; w: number; h: number } | null>(null);
  const decodingRef    = useRef(false);
  const hasFrameRef    = useRef(false);
  const [hasFrame, setHasFrame] = useState(false);

  const id = serialToId(device.serial);
  const dw = device.screen_width  || 1080;
  const dh = device.screen_height || 1920;

  useEffect(() => {
    if (device.state === 'DISCONNECTED' || device.state === 'DEAD') {
      hasFrameRef.current = false;
      setHasFrame(false);
    }
  }, [device.state]);

  // ── Frame subscription ──────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Ensure canvas dimensions match device
    canvas.width  = dw;
    canvas.height = dh;

    // Lazy-init H264 decoder
    if (!h264DecoderRef.current) h264DecoderRef.current = new H264CanvasDecoder();
    const h264 = h264DecoderRef.current;
    h264.attach(canvas, () => {
      if (overlayRef.current) overlayRef.current.style.display = 'none';
      setHasFrame(true);
    });

    // Decode the latest pending JPEG — only one decode in-flight at a time.
    // If a newer frame arrives while decoding, it replaces pendingJpegRef and
    // gets decoded immediately after, so we always render the most recent frame.
    function drainJpeg() {
      const pending = pendingJpegRef.current;
      if (!pending || decodingRef.current) return;
      pendingJpegRef.current = null;
      decodingRef.current = true;

      createImageBitmap(new Blob([pending.data], { type: 'image/jpeg' })).then((bmp) => {
        decodingRef.current = false;
        const cv = canvasRef.current;
        if (!cv) { bmp.close(); return; }

        // Only resize when dimensions actually change — resizing always clears the canvas.
        if (cv.width !== pending.w || cv.height !== pending.h) {
          cv.width  = pending.w;
          cv.height = pending.h;
        }

        const ctx = cv.getContext('2d');
        // Always scale the JPEG to the current canvas size.
        // (Agent may downscale JPEG for performance, while the canvas keeps the full device aspect.)
        if (ctx) ctx.drawImage(bmp, 0, 0, cv.width, cv.height);
        bmp.close();

        if (!hasFrameRef.current) {
          hasFrameRef.current = true;
          if (overlayRef.current) overlayRef.current.style.display = 'none';
          setHasFrame(true);
        }

        // FPS counter — ring-buffer approach avoids a new array every frame
        const now = performance.now();
        fpsTimesRef.current.push(now);
        // Trim once per second worth of entries (keep only last-1000ms)
        const cutoff = now - 1000;
        let i = 0;
        while (i < fpsTimesRef.current.length && fpsTimesRef.current[i] < cutoff) i++;
        if (i > 0) fpsTimesRef.current.splice(0, i);
        if (fpsRef.current) fpsRef.current.textContent = `${fpsTimesRef.current.length} FPS`;

        // A newer frame may have arrived while we were decoding — process it now.
        drainJpeg();
      }).catch(() => { decodingRef.current = false; });
    }

    const handleFrame = (evt: FrameEvent) => {
      if (evt.type === 'jpeg') {
        // Store the latest frame; drainJpeg will pick it up.
        // If a decode is already in-flight we just update the pending slot —
        // the in-flight decode will call drainJpeg() on completion.
        pendingJpegRef.current = {
          data: evt.data,
          // Keep canvas sizing stable for correct touch mapping.
          w: dw,
          h: dh,
        };
        drainJpeg();
        return;
      }

      if (evt.type === 'h264_config') { h264.handleConfig(evt); return; }
      if (evt.type === 'h264_key' || evt.type === 'h264_delta') {
        h264.handleFrame(evt);
        const now = performance.now();
        fpsTimesRef.current.push(now);
        const cutoff = now - 1000;
        let i = 0;
        while (i < fpsTimesRef.current.length && fpsTimesRef.current[i] < cutoff) i++;
        if (i > 0) fpsTimesRef.current.splice(0, i);
        if (fpsRef.current) fpsRef.current.textContent = `${fpsTimesRef.current.length} FPS`;
      }
    };

    const unsub = FrameDispatcher.subscribe(device.serial, handleFrame);
    return () => {
      unsub();
      h264.detach();
    };
  }, [device.serial, dw, dh]);

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
          wsSend({ type: 'swipe', serial: device.serial, x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y, ms: Math.min(elapsed, 1000) });
        }
      },
    },
    { drag: { threshold: 5 }, pointer: { touch: true }, event: { passive: false } }
  );

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (mode !== 'tap' || draggedRef.current) { draggedRef.current = false; return; }
      const el   = (e.target as HTMLElement) ?? e.currentTarget;
      const rect = el.getBoundingClientRect();
      const p    = clientToDevice(e.clientX - rect.left, e.clientY - rect.top, rect.width, rect.height);
      wsSend({ type: 'tap', serial: device.serial, x: p.x, y: p.y });
      if (onTap && rect.width > 0 && rect.height > 0) {
        onTap((e.clientX - rect.left) / rect.width, (e.clientY - rect.top) / rect.height);
      }
    },
    [mode, clientToDevice, wsSend, device.serial, onTap]
  );

  return (
    <>
      <div
        {...bind()}
        ref={wrapRef}
        onClick={handleClick}
        className={`relative w-full overflow-hidden rounded-md border border-border bg-black ${
          mode === 'swipe' ? 'cursor-crosshair' : 'cursor-pointer'
        }`}
        style={{ aspectRatio: `${dw}/${dh}` }}
        id={`wrap-${id}`}
      >
        {/* Single canvas — no <img> tag double-render */}
        <canvas
          ref={canvasRef}
          className='absolute inset-0 h-full w-full'
          width={dw}
          height={dh}
          style={{ imageRendering: 'auto' }}
        />
        <div
          ref={overlayRef}
          className='absolute inset-0 flex items-center justify-center text-xs text-muted-foreground'
          id={`overlay-${id}`}
          style={{ pointerEvents: 'none', display: hasFrame ? 'none' : undefined }}
        />
        <div
          ref={fpsRef}
          className='pointer-events-none absolute right-1 top-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-mono text-white'
          id={`fps-${id}`}
        >
          0 FPS
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
