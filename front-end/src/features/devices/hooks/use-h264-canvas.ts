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
import {
  subscribeBinaryFrames,
  getLastConfigFrame,
  getLastKeyFrame,
  subscribeDeviceFarm,
  requestIdr,
  isCachedKeyFrameStale,
  notifyDecoderBackpressure,
  discardCachedH264KeyFrame
} from '../services/ws';
import { h264HardwareFailureRegistry } from '../services/h264-hardware-failure';

const H264_CANVAS_DEBUG = false;

function postWorkerReset(worker: Worker, serial: string): void {
  worker.postMessage({
    type: 'reset',
    retryHardware: !h264HardwareFailureRegistry.has(serial)
  });
}

export function useH264Video(
  serial: string,
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  opts?: {
    restartKey?: number;
    onFrame?: (frame?: { mostlyBlack: boolean }) => void;
    onStall?: (reason: 'no_packets' | 'decoder_stalled') => void;
    inspectFramesForBlack?: boolean;
    notifyStallWithVisibleFrame?: boolean;
    visibleFrameRecoveryMinIntervalMs?: number;
    renderedFrameStaleMs?: number;
    onStats?: (stats: {
      decodeQueueSize: number;
      droppedDelta: number;
      decodedFrames: number;
      accel: string;
    }) => void;
  }
) {
  const restartKey = opts?.restartKey ?? 0;
  const workerRef = useRef<Worker | null>(null);
  const rafRef = useRef<number | null>(null);
  const renderCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const renderCtxRef = useRef<CanvasRenderingContext2D | null>(null);
  const blackProbeRef = useRef<BlackFrameProbe | null>(null);
  const mountedAtRef = useRef(0);
  const lastVideoPacketAtRef = useRef(0);
  const lastRenderedFrameAtRef = useRef(0);
  const lastRecoveryAtRef = useRef(0);

  // Unblock the worker's frameInFlight gate on decoder reset. Push model renders
  // immediately so there is no pending VideoFrame in a ref; this just resets the
  // worker's in-flight flag so it resumes pumping after a reset/reconnect.
  const clearLatestFrame = () => {
    workerRef.current?.postMessage({ type: 'frame-consumed' });
  };
  const onFrameRef = useRef(opts?.onFrame);
  const onStallRef = useRef(opts?.onStall);
  const onStatsRef = useRef(opts?.onStats);
  const inspectFramesForBlackRef = useRef(opts?.inspectFramesForBlack ?? true);
  const notifyStallWithVisibleFrameRef = useRef(
    opts?.notifyStallWithVisibleFrame
  );
  const visibleFrameRecoveryMinIntervalMsRef = useRef(
    opts?.visibleFrameRecoveryMinIntervalMs ?? 3000
  );
  const renderedFrameStaleMsRef = useRef(opts?.renderedFrameStaleMs ?? 5000);
  const serialRef = useRef(serial);
  const wsConnectedRef = useRef(false);
  // Reset+replay on ws_status=true is only needed for true reconnects (close→open).
  // On initial mount, the worker is fresh and bootstrap cache replay already
  // handles init — an unconditional reset here would wipe a just-initialized
  // decoder and leave the browser black until the next IDR (up to ~14s).
  const everDisconnectedRef = useRef(false);

  onFrameRef.current = opts?.onFrame;
  onStallRef.current = opts?.onStall;
  onStatsRef.current = opts?.onStats;
  inspectFramesForBlackRef.current = opts?.inspectFramesForBlack ?? true;
  notifyStallWithVisibleFrameRef.current = opts?.notifyStallWithVisibleFrame;
  visibleFrameRecoveryMinIntervalMsRef.current =
    opts?.visibleFrameRecoveryMinIntervalMs ?? 3000;
  renderedFrameStaleMsRef.current = opts?.renderedFrameStaleMs ?? 5000;
  serialRef.current = serial;

  // ── Main lifecycle: spawn worker + subscribe to frames ───────────────────
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!serial) {
      mountedAtRef.current = 0;
      lastVideoPacketAtRef.current = 0;
      lastRenderedFrameAtRef.current = 0;
      lastRecoveryAtRef.current = 0;
      return;
    }
    if (!('VideoDecoder' in window)) {
      console.warn('[H264] WebCodecs not supported in this browser');
      return;
    }

    const worker = new Worker('/h264-worker.js?v=46');
    workerRef.current = worker;
    mountedAtRef.current = Date.now();

    worker.postMessage({
      type: 'init',
      preferHardware: !h264HardwareFailureRegistry.has(serial)
    });

    const getRenderContext = (canvas: HTMLCanvasElement) => {
      if (renderCanvasRef.current !== canvas) {
        renderCanvasRef.current = canvas;
        renderCtxRef.current = canvas.getContext('2d', {
          alpha: false,
          desynchronized: true
        });
      }
      return renderCtxRef.current;
    };

    // Render frame immediately when worker pushes it. Use 2D canvas instead of
    // WebGL: WebCodecs VideoFrame -> WebGL texture is GPU/driver-sensitive and
    // can silently produce a black canvas on some Chrome/macOS combinations.
    const renderFrame = (frame: VideoFrame, w: number, h: number) => {
      const canvas = canvasRef.current;
      if (!canvas) {
        try {
          frame.close();
        } catch {
          /* ok */
        }
        return;
      }
      try {
        const width = Math.max(1, Math.floor(w || frame.displayWidth || 1));
        const height = Math.max(1, Math.floor(h || frame.displayHeight || 1));
        if (canvas.width !== width || canvas.height !== height) {
          canvas.width = width;
          canvas.height = height;
        }
        const ctx = getRenderContext(canvas);
        if (!ctx) return;
        ctx.drawImage(frame, 0, 0, width, height);
        const mostlyBlack = inspectFramesForBlackRef.current
          ? isFrameMostlyBlack(frame, width, height, blackProbeRef)
          : false;
        lastRenderedFrameAtRef.current = Date.now();
        onFrameRef.current?.({ mostlyBlack });
      } catch (err) {
        if (H264_CANVAS_DEBUG) console.debug('[H264] render skipped:', err);
      } finally {
        try {
          frame.close();
        } catch {
          /* ok */
        }
      }
    };

    // RAF sends pull-frame as fallback for missed pushes (decoder reset, tab restore).
    const keepalive = () => {
      workerRef.current?.postMessage({ type: 'pull-frame' });
      rafRef.current = requestAnimationFrame(keepalive);
    };
    rafRef.current = requestAnimationFrame(keepalive);

    worker.onmessage = ({ data }) => {
      if (workerRef.current !== worker || serialRef.current !== serial) {
        if (data.type === 'frame' && data.frame) {
          try {
            data.frame.close();
          } catch {
            /* ok */
          }
        }
        return;
      }
      if (data.type === 'error')
        console.error('[H264] worker error:', data.message);
      if (data.type === 'hardware-fallback') {
        h264HardwareFailureRegistry.remember(serial);
        return;
      }
      if (data.type === 'decoder-error') {
        const now = Date.now();
        const s = serial;
        const w = worker;
        const hasVisibleFrame = lastRenderedFrameAtRef.current > 0;
        const recoveryMinInterval = hasVisibleFrame
          ? visibleFrameRecoveryMinIntervalMsRef.current
          : 700;
        if (s && w && now - lastRecoveryAtRef.current > recoveryMinInterval) {
          lastRecoveryAtRef.current = now;
          onStallRef.current?.('decoder_stalled');
          discardCachedH264KeyFrame(s);
          w.postMessage({ type: 'reset', retryHardware: false });
          clearLatestFrame();
          setTimeout(() => requestIdr(s, 0), 30);
        }
        return;
      }
      if (data.type === 'decoder-backpressure') {
        notifyDecoderBackpressure(serial, 500);
        return;
      }
      if (data.type === 'frame' && data.frame) {
        renderFrame(
          data.frame as VideoFrame,
          data.width as number,
          data.height as number
        );
        worker.postMessage({ type: 'frame-consumed' });
      }
      if (data.type === 'stats') {
        onStatsRef.current?.({
          decodeQueueSize: Number(data.decodeQueueSize ?? 0),
          droppedDelta: Number(data.droppedDelta ?? 0),
          decodedFrames: Number(data.decodedFrames ?? 0),
          accel: String(data.accel ?? '')
        });
        if (H264_CANVAS_DEBUG) {
          console.debug(
            '[H264] stats',
            `q=${data.decodeQueueSize} dropped=${data.droppedDelta} decoded=${data.decodedFrames} accel=${data.accel}`
          );
        }
      }
    };
    worker.onerror = (e) =>
      console.error('[H264] worker load error:', e.message);

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
      if (frameType === 0x11) lastVideoPacketAtRef.current = Date.now();

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
      mountedAtRef.current = 0;
      postWorkerReset(worker, serial);
      worker.terminate();
      if (workerRef.current === worker) workerRef.current = null;
      renderCanvasRef.current = null;
      renderCtxRef.current = null;
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      // Push model: frames are rendered and closed immediately — no pending ref to clean up.
    };
  }, [canvasRef, serial, restartKey]);

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
      requestIdr(serialValue, 0);
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
        const ptsUs = ptsHi <= 0x1fffff ? ptsHi * 4_294_967_296 + ptsLo : 0;
        const frameData = new Uint8Array(keyBuf, doff + 9).slice();
        if (frameData.length > 0 && isKey) {
          w.postMessage(
            { type: 'frame', isKey: true, ptsUs, frameData: frameData.buffer },
            [frameData.buffer]
          );
        }
      }
    }
  };

  useEffect(() => {
    const w = workerRef.current;
    if (!w) return;

    lastVideoPacketAtRef.current = 0;
    lastRenderedFrameAtRef.current = 0;
    lastRecoveryAtRef.current = 0;
    mountedAtRef.current = Date.now();
    postWorkerReset(w, serial);
    clearLatestFrame();
    if (!serial) return;
    replayCachedBootstrap(w, serial);
    // Always ask server for a fresh IDR on mount / serial change.
    // The bootstrap cache covers fast path (~50ms replay), but the cache may
    // be stale or missing; the server-forced IDR lands within ~100ms and
    // guarantees decoder sync even if no prior viewer primed the cache.
    requestIdr(serial, 0);
  }, [serial, restartKey]);

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
      if (!everDisconnectedRef.current) {
        // Initial connect after mount: requestIdr on mount may have raced an
        // opening socket (common on client-side navigation). Prime the stream now.
        const s = serialRef.current;
        if (s) {
          setTimeout(() => requestIdr(s, 0), 50);
        }
        return;
      }
      everDisconnectedRef.current = false;
      const w = workerRef.current;
      const s = serialRef.current;
      if (!w || !s) return;
      postWorkerReset(w, s);
      clearLatestFrame();
      // Allow ws.ts cache replay microtask to settle before bootstrap replay.
      setTimeout(() => {
        replayCachedBootstrap(w, s);
        requestIdr(s, 0);
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
      postWorkerReset(w, s);
      clearLatestFrame();
      // Push model: worker pumps frames on its own. frame-consumed unblocks
      // the worker's frameInFlight gate in case it stalled while hidden.
      setTimeout(() => {
        replayCachedBootstrap(w, s);
        requestIdr(s, 0);
      }, 30);
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, []);

  // Runtime freeze recovery: the WS can stay open and keep receiving H264
  // packets while WebCodecs stops producing frames (bad P-frame chain, decoder
  // hiccup, GPU/context stall). In that state the canvas keeps showing the last
  // good frame forever, so periodically ask for a fresh IDR and reset decoder.
  useEffect(() => {
    const timer = setInterval(() => {
      const s = serialRef.current;
      const w = workerRef.current;
      if (!s || !w) return;
      if (
        typeof document !== 'undefined' &&
        document.visibilityState !== 'visible'
      )
        return;

      const now = Date.now();
      const mountedAt = mountedAtRef.current;
      const lastPacketAt = lastVideoPacketAtRef.current;
      const lastRenderedAt = lastRenderedFrameAtRef.current;
      if (!lastPacketAt) {
        if (
          mountedAt &&
          now - mountedAt > 3000 &&
          now - lastRecoveryAtRef.current > 3000
        ) {
          lastRecoveryAtRef.current = now;
          requestIdr(s, 0);
          if (!lastRenderedAt || notifyStallWithVisibleFrameRef.current) {
            onStallRef.current?.('no_packets');
          }
        }
        return;
      }

      const packetAgeMs = now - lastPacketAt;
      const renderedAgeMs = lastRenderedAt ? now - lastRenderedAt : Infinity;

      // If no video packets are arriving before the first rendered frame, this is
      // likely a startup/transport stall. After a valid frame is visible, however,
      // scrcpy may legitimately emit no packets on a static screen; keep the last
      // canvas frame instead of resetting the decoder and creating recovery churn.
      if (packetAgeMs > 3000 && now - lastRecoveryAtRef.current > 3000) {
        if (lastRenderedAt && !notifyStallWithVisibleFrameRef.current) {
          return;
        }
        lastRecoveryAtRef.current = now;
        if (!lastRenderedAt) {
          postWorkerReset(w, s);
          clearLatestFrame();
        }
        requestIdr(s, 0);
        if (!lastRenderedAt || notifyStallWithVisibleFrameRef.current) {
          onStallRef.current?.('no_packets');
        }
        return;
      }

      // Packets are arriving but no frame has rendered recently: reset the
      // browser decoder and request a keyframe to rebuild the reference chain.
      // The detail screen must recover faster than the user's perception of a
      // frozen mirror. Packets flowing without rendered frames means the browser
      // decoder/canvas path is stale even if the backend stream is healthy.
      const renderedStaleMs = lastRenderedAt
        ? renderedFrameStaleMsRef.current
        : 1800;
      const visibleRecoveryMinInterval =
        lastRenderedAt > 0
          ? visibleFrameRecoveryMinIntervalMsRef.current
          : 3000;
      if (
        packetAgeMs < 2000 &&
        renderedAgeMs > renderedStaleMs &&
        now - lastRecoveryAtRef.current > visibleRecoveryMinInterval
      ) {
        lastRecoveryAtRef.current = now;
        onStallRef.current?.('decoder_stalled');
        postWorkerReset(w, s);
        clearLatestFrame();
        setTimeout(() => {
          replayCachedBootstrap(w, s);
          requestIdr(s, 0);
        }, 30);
      }
    }, 1000);
    return () => clearInterval(timer);
  }, []);
}

type BlackFrameProbe = {
  canvas: HTMLCanvasElement | OffscreenCanvas;
  ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;
};

function getBlackFrameProbe(
  probeRef: React.MutableRefObject<BlackFrameProbe | null>
): BlackFrameProbe | null {
  if (probeRef.current) return probeRef.current;
  let canvas: HTMLCanvasElement | OffscreenCanvas;
  if (typeof OffscreenCanvas !== 'undefined') {
    canvas = new OffscreenCanvas(32, 32);
  } else if (typeof document !== 'undefined') {
    canvas = document.createElement('canvas');
    canvas.width = 32;
    canvas.height = 32;
  } else {
    return null;
  }
  const ctx = canvas.getContext('2d', {
    alpha: false,
    willReadFrequently: true
  });
  if (!ctx) return null;
  probeRef.current = { canvas, ctx };
  return probeRef.current;
}

function isFrameMostlyBlack(
  frame: VideoFrame,
  width: number,
  height: number,
  probeRef: React.MutableRefObject<BlackFrameProbe | null>
): boolean {
  const sampleW = Math.min(32, width);
  const sampleH = Math.min(32, height);
  const x = Math.max(0, Math.floor((width - sampleW) / 2));
  const y = Math.max(0, Math.floor((height - sampleH) / 2));
  const probe = getBlackFrameProbe(probeRef);
  if (!probe) return false;
  if (probe.canvas.width !== sampleW) probe.canvas.width = sampleW;
  if (probe.canvas.height !== sampleH) probe.canvas.height = sampleH;
  let data: Uint8ClampedArray;
  try {
    probe.ctx.drawImage(frame, x, y, sampleW, sampleH, 0, 0, sampleW, sampleH);
    data = probe.ctx.getImageData(0, 0, sampleW, sampleH).data;
  } catch {
    return false;
  }
  let dark = 0;
  let lit = 0;
  const total = sampleW * sampleH;
  for (let i = 0; i < data.length; i += 4) {
    const luma = data[i] * 0.2126 + data[i + 1] * 0.7152 + data[i + 2] * 0.0722;
    if (luma < 8) dark += 1;
    if (luma > 24) lit += 1;
  }
  return dark / total > 0.985 && lit / total < 0.01;
}
