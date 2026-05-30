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
  notifyDecoderBackpressure
} from '../services/ws';

export function useH264Video(
  serial: string,
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  opts?: {
    restartKey?: number;
    onFrame?: (frame?: { mostlyBlack: boolean }) => void;
    onStall?: (reason: 'no_packets' | 'decoder_stalled') => void;
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

    const worker = new Worker('/h264-worker.js?v=26');
    workerRef.current = worker;
    mountedAtRef.current = Date.now();

    worker.postMessage({ type: 'init' });

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
        const ctx = canvas.getContext('2d', { alpha: false });
        if (!ctx) return;
        ctx.drawImage(frame, 0, 0, width, height);
        const mostlyBlack = isCanvasMostlyBlack(ctx, width, height);
        lastRenderedFrameAtRef.current = Date.now();
        onFrameRef.current?.({ mostlyBlack });
      } catch (err) {
        console.debug('[H264] render skipped:', err);
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
      if (data.type === 'error')
        console.error('[H264] worker error:', data.message);
      if (data.type === 'decoder-error') {
        const now = Date.now();
        const s = serialRef.current;
        const w = workerRef.current;
        if (s && w && now - lastRecoveryAtRef.current > 700) {
          lastRecoveryAtRef.current = now;
          onStallRef.current?.('decoder_stalled');
          w.postMessage({ type: 'reset' });
          clearLatestFrame();
          setTimeout(() => requestIdr(s, 0), 30);
        }
        return;
      }
      if (data.type === 'decoder-backpressure') {
        const s = serialRef.current;
        if (s) {
          notifyDecoderBackpressure(s, 500);
        }
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
        console.debug(
          '[H264] stats',
          `q=${data.decodeQueueSize} dropped=${data.droppedDelta} decoded=${data.decodedFrames} accel=${data.accel}`
        );
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
      worker.postMessage({ type: 'reset' });
      worker.terminate();
      workerRef.current = null;
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      // Push model: frames are rendered and closed immediately — no pending ref to clean up.
    };
  }, [serial, restartKey]);

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
    w.postMessage({ type: 'reset' });
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
      w.postMessage({ type: 'reset' });
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
      w.postMessage({ type: 'reset' });
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
          onStallRef.current?.('no_packets');
          requestIdr(s, 0);
        }
        return;
      }

      const packetAgeMs = now - lastPacketAt;
      const renderedAgeMs = lastRenderedAt ? now - lastRenderedAt : Infinity;

      // If no video packets are arriving, this is likely a transport/agent stall;
      // an IDR request is cheap and avoids waiting for the next user interaction.
      // Do not mark the stream stalled when a valid frame is already visible:
      // scrcpy may emit very few frames on a static screen.
      if (packetAgeMs > 3000 && now - lastRecoveryAtRef.current > 3000) {
        lastRecoveryAtRef.current = now;
        requestIdr(s, 0);
        if (!lastRenderedAt) {
          onStallRef.current?.('no_packets');
        }
        return;
      }

      // Packets are arriving but no frame has rendered recently: reset the
      // browser decoder and request a keyframe to rebuild the reference chain.
      if (
        packetAgeMs < 2000 &&
        renderedAgeMs > 1800 &&
        now - lastRecoveryAtRef.current > 1500
      ) {
        lastRecoveryAtRef.current = now;
        onStallRef.current?.('decoder_stalled');
        w.postMessage({ type: 'reset' });
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

function isCanvasMostlyBlack(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number
): boolean {
  const sampleW = Math.min(32, width);
  const sampleH = Math.min(32, height);
  const x = Math.max(0, Math.floor((width - sampleW) / 2));
  const y = Math.max(0, Math.floor((height - sampleH) / 2));
  let data: Uint8ClampedArray;
  try {
    data = ctx.getImageData(x, y, sampleW, sampleH).data;
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
