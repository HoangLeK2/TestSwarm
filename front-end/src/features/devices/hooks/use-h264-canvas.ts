'use client';

/**
 * useH264Video — zero-latency H264 decode via WebCodecs VideoDecoder in a Web Worker.
 *
 * Worker runs off the main thread (Web Worker + OffscreenCanvas) so React
 * rendering never stalls decode. WebCodecs decodes frame-by-frame with no
 * MSE buffering — latency is typically 1-2 frames (33-66 ms at 30 fps).
 *
 * ws.ts caches last config (0x10) + last keyframe (0x11 is_key=1) per serial
 * and replays them via queueMicrotask when subscribing. This ensures the worker
 * gets SPS/PPS + an IDR immediately on mount without waiting up to 14 s.
 */

import { useEffect, useRef } from 'react';
import { subscribeBinaryFrames, getLastConfigFrame, getLastKeyFrame, subscribeDeviceFarm, requestIdr, isCachedKeyFrameStale } from '../services/ws';
import { WebGLRenderer } from '../lib/webgl-renderer';

export function useH264Video(
  serial: string,
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  opts?: {
    onFrame?: () => void;
    onStats?: (stats: {
      decodeQueueSize: number;
      droppedDelta: number;
      decodedFrames: number;
      accel: string;
    }) => void;
  }
) {
  const workerRef  = useRef<Worker | null>(null);
  const rendererRef = useRef<WebGLRenderer | null>(null);
  const rafRef     = useRef<number | null>(null);
  const latestFrameRef = useRef<VideoFrame | null>(null);
  const latestSizeRef = useRef<{ w: number; h: number }>({ w: 0, h: 0 });

  // Drop any in-memory VideoFrame and tell worker the slot is free. Call on
  // every decoder reset. Without this, a frame that was pending when the tab
  // went hidden stays in ref — its underlying GPU buffer may be invalidated
  // when Chrome suspends the page, so drawLatest silently fails on return,
  // while the worker's frameInFlight stays true → no new frames pumped → black.
  const clearLatestFrame = () => {
    const pending = latestFrameRef.current;
    if (pending && typeof pending.close === 'function') {
      try { pending.close(); } catch { /* already closed */ }
    }
    latestFrameRef.current = null;
    latestSizeRef.current = { w: 0, h: 0 };
    workerRef.current?.postMessage({ type: 'frame-consumed' });
  };
  const onFrameRef = useRef(opts?.onFrame);
  const onStatsRef = useRef(opts?.onStats);
  const serialRef  = useRef(serial);
  const wsConnectedRef = useRef(false);
  // Reset+replay on ws_status=true is only needed for true reconnects (close→open).
  // On initial mount, the worker is fresh and bootstrap cache replay already
  // handles init — an unconditional reset here would wipe a just-initialized
  // decoder and leave the browser black until the next IDR (up to ~14s).
  const everDisconnectedRef = useRef(false);

  onFrameRef.current = opts?.onFrame;
  onStatsRef.current = opts?.onStats;
  serialRef.current  = serial;

  // ── Main lifecycle: spawn worker + subscribe to frames ───────────────────
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!('VideoDecoder' in window)) {
      console.warn('[H264] WebCodecs not supported in this browser');
      return;
    }

    const worker = new Worker('/h264-worker.js?v=19');
    workerRef.current = worker;

    const drawLatest = () => {
      const canvas = canvasRef.current;
      const frame = latestFrameRef.current;
      if (canvas && frame) {
        try {
          let renderer = rendererRef.current;
          if (!renderer) {
            renderer = new WebGLRenderer(canvas);
            rendererRef.current = renderer;
          }
          if (renderer) {
            const { w, h } = latestSizeRef.current;
            // texImage2D can throw InvalidStateError when the VideoFrame's
            // underlying GPU buffer was invalidated by the browser (e.g. the
            // page was suspended while hidden). Swallow so the RAF chain
            // keeps turning — the next decoded frame will render fine.
            try {
              renderer.render(frame, w, h);
              onFrameRef.current?.();
            } catch (err) {
              console.debug('[H264] render skipped (invalidated frame):', err);
            }
          }
        } finally {
          if (typeof frame.close === 'function') {
            try { frame.close(); } catch { /* already closed */ }
          }
          latestFrameRef.current = null;
          workerRef.current?.postMessage({ type: 'frame-consumed' });
        }
      }
      // Hard-sync decode handoff with display loop: pull at most one frame per RAF tick.
      workerRef.current?.postMessage({ type: 'pull-frame' });
      rafRef.current = requestAnimationFrame(drawLatest);
    };
    rafRef.current = requestAnimationFrame(drawLatest);

    worker.onmessage = ({ data }) => {
      if (data.type === 'error') console.error('[H264] worker reported error:', data.message);
      if (data.type === 'frame' && data.frame) {
        // Latest-frame-only mode: replace pending frame, close old one.
        const prev = latestFrameRef.current;
        if (prev && typeof prev.close === 'function') prev.close();
        latestFrameRef.current = data.frame as VideoFrame;
        latestSizeRef.current = { w: data.width as number, h: data.height as number };
      }
      if (data.type === 'stats') {
        onStatsRef.current?.({
          decodeQueueSize: Number(data.decodeQueueSize ?? 0),
          droppedDelta: Number(data.droppedDelta ?? 0),
          decodedFrames: Number(data.decodedFrames ?? 0),
          accel: String(data.accel ?? ''),
        });
        // Useful for diagnosing browser decode bottlenecks in production logs.
        console.debug(
          '[H264] stats',
          `q=${data.decodeQueueSize} dropped=${data.droppedDelta} decoded=${data.decodedFrames} accel=${data.accel}`
        );
      }
    };
    worker.onerror = (e) => console.error('[H264] worker load error:', e.message);

    // Worker only decodes and sends VideoFrame; drawing is done by main-thread RAF loop.
    worker.postMessage({ type: 'init' });

    // Subscribe to binary frames synchronously.
    // ws.ts replays cached config + keyframe via queueMicrotask so they land
    // right after this effect returns — worker is already ready by then.
    const unsubscribe = subscribeBinaryFrames((buf: ArrayBuffer) => {
      const w = workerRef.current;
      if (!w || buf.byteLength < 2) return;

      let view: DataView;
      try {
        view = new DataView(buf);
      } catch {
        return;
      }
      const frameType = view.getUint8(0);
      if (frameType !== 0x10 && frameType !== 0x11) return;

      const slen = view.getUint8(1);
      if (buf.byteLength < 2 + slen + 4) return;
      const doff = 2 + slen + 4; // skip serial + w/h

      if (frameType === 0x10) {
        if (buf.byteLength < doff + 2) return;
        // Clone before transfer because multiple device hooks share one WS frame.
        const frame = buf.slice(0);
        w.postMessage({ type: 'binary', frameType: 0x10, buf: frame }, [frame]);
        return;
      }

      if (frameType === 0x11) {
        if (buf.byteLength < doff + 9) return;
        // Clone before transfer because multiple device hooks share one WS frame.
        const frame = buf.slice(0);
        w.postMessage({ type: 'binary', frameType: 0x11, buf: frame }, [frame]);
      }
    }, serial);

    return () => {
      unsubscribe();
      worker.postMessage({ type: 'reset' });
      worker.terminate();
      workerRef.current = null;
      if (rendererRef.current) {
        rendererRef.current.dispose();
        rendererRef.current = null;
      }
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      const pending = latestFrameRef.current;
      if (pending && typeof pending.close === 'function') pending.close();
      latestFrameRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Reset when serial changes, then immediately replay cached config+IDR ──
  // Without replay, the worker sits with decoder=null until the next live IDR
  // (3-14 s depending on device). With replay, it decodes within ~50 ms.
  const replayCachedBootstrap = (w: Worker, serialValue: string) => {
    if (!serialValue) return;
    // Replay config (SPS/PPS)
    const cfgBuf = getLastConfigFrame(serialValue);
    if (cfgBuf) {
      let view: DataView;
      try {
        view = new DataView(cfgBuf);
      } catch {
        return;
      }
      const slen = view.getUint8(1);
      const doff = 2 + slen + 4;
      if (cfgBuf.byteLength >= doff + 2) {
        const avcc = new Uint8Array(cfgBuf, doff + 1).slice();
        if (avcc.length >= 4) {
          w.postMessage({ type: 'config', avcc: avcc.buffer }, [avcc.buffer]);
        }
      }
    }

    // Replay last keyframe — live P-frames after this IDR remain valid refs.
    // Skip when stale: a cached keyframe older than ~5s may predate a newer
    // IDR that arrived while the tab was hidden, so replaying it drifts the
    // decoder. The server-side forced IDR (requested below) fills the gap.
    if (isCachedKeyFrameStale(serialValue)) {
      requestIdr(serialValue);
      return;
    }
    const keyBuf = getLastKeyFrame(serialValue);
    if (keyBuf) {
      let view: DataView;
      try {
        view = new DataView(keyBuf);
      } catch {
        return;
      }
      const slen = view.getUint8(1);
      const doff = 2 + slen + 4;
      if (keyBuf.byteLength >= doff + 9) {
        const isKey = view.getUint8(doff) !== 0;
        const ptsHi = view.getUint32(doff + 1, false);
        const ptsLo = view.getUint32(doff + 5, false);
        // Safe-number bound for (hi << 32) | lo within JS Number precision:
        // hi must be <= 2^21 - 1.
        const ptsUs = ptsHi <= 0x1fffff ? (ptsHi * 4_294_967_296 + ptsLo) : 0;
        const frameData = new Uint8Array(keyBuf, doff + 9).slice();
        if (frameData.length > 0 && isKey) {
          w.postMessage(
            { type: 'frame', isKey: true, ptsUs, frameData: frameData.buffer },
            [frameData.buffer],
          );
        }
      }
    }
  };

  useEffect(() => {
    const w = workerRef.current;
    if (!w) return;

    w.postMessage({ type: 'reset' });
    clearLatestFrame();
    if (!serial) return;
    replayCachedBootstrap(w, serial);
    // Always ask server for a fresh IDR on mount / serial change.
    // The bootstrap cache covers fast path (~50ms replay), but the cache may
    // be stale or missing; the server-forced IDR lands within ~100ms and
    // guarantees decoder sync even if no prior viewer primed the cache.
    requestIdr(serial);
  }, [serial]);

  // Reconnect warm-up: WS reconnect often leaves decoder on stale refs.
  // Refresh worked because it recreated hook+worker; do that automatically.
  // Only trigger on true close→open reconnects. Initial open is handled by
  // the bootstrap cache replay in the effect above — resetting there would
  // wipe a just-initialized decoder and leave the browser black.
  useEffect(() => {
    const unsub = subscribeDeviceFarm((msg) => {
      if (msg.type !== 'ws_status') return;
      const next = Boolean(msg.connected);
      wsConnectedRef.current = next;
      if (!next) {
        everDisconnectedRef.current = true;
        return;
      }
      if (!everDisconnectedRef.current) return; // initial connect — no reset
      everDisconnectedRef.current = false;
      const w = workerRef.current;
      const s = serialRef.current;
      if (!w || !s) return;
      w.postMessage({ type: 'reset' });
      clearLatestFrame();
      // Allow ws.ts cache replay microtask to settle before bootstrap replay.
      setTimeout(() => {
        replayCachedBootstrap(w, s);
        requestIdr(s);
      }, 30);
    });
    return () => unsub();
  }, []);

  // Tab visibility recovery: Chrome pauses RAF + throttles WebCodecs when tab
  // hidden. On return, P-frames in-flight reference an IDR the decoder no
  // longer holds, so canvas stays black until next natural IDR (up to ~14s).
  // Reset decoder, drop the invalidated VideoFrame, replay cache (if fresh),
  // and ask server for a forced IDR.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return;
      const w = workerRef.current;
      const s = serialRef.current;
      if (!w || !s) return;
      w.postMessage({ type: 'reset' });
      clearLatestFrame();
      // Kick the RAF chain in case the browser didn't resume it cleanly
      // (extreme cases after long hide windows).
      if (rafRef.current == null) {
        // Guard: drawLatest is hoisted inside the mount effect. We can't
        // reach it from here. Re-posting pull-frame unblocks the worker,
        // and the next natural RAF tick will resume drawing.
        workerRef.current?.postMessage({ type: 'pull-frame' });
      }
      setTimeout(() => {
        replayCachedBootstrap(w, s);
        requestIdr(s);
      }, 30);
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, []);
}
