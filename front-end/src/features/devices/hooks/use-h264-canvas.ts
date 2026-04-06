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
import { subscribeBinaryFrames, getLastConfigFrame, getLastKeyFrame } from '../services/ws';

export function useH264Video(
  serial: string,
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  opts?: { onFrame?: () => void }
) {
  const workerRef  = useRef<Worker | null>(null);
  const onFrameRef = useRef(opts?.onFrame);
  const serialRef  = useRef(serial);

  onFrameRef.current = opts?.onFrame;
  serialRef.current  = serial;

  // ── Main lifecycle: spawn worker + subscribe to frames ───────────────────
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!('VideoDecoder' in window)) {
      console.warn('[H264] WebCodecs not supported in this browser');
      return;
    }

    const worker = new Worker('/h264-worker.js?v=10');
    workerRef.current = worker;

    worker.onmessage = ({ data }) => {
      if (data.type === 'fps') onFrameRef.current?.();
      if (data.type === 'error') console.error('[H264] worker reported error:', data.message);
    };
    worker.onerror = (e) => console.error('[H264] worker load error:', e.message);

    // Transfer canvas control to worker
    const canvas = canvasRef.current;
    if (canvas && typeof (canvas as HTMLCanvasElement).transferControlToOffscreen === 'function') {
      try {
        const offscreen = (canvas as HTMLCanvasElement).transferControlToOffscreen();
        worker.postMessage({ type: 'init', canvas: offscreen }, [offscreen]);
      } catch (e) {
        console.warn('[H264] transferControlToOffscreen failed:', e);
      }
    }

    // Subscribe to binary frames synchronously.
    // ws.ts replays cached config + keyframe via queueMicrotask so they land
    // right after this effect returns — worker is already ready by then.
    const unsubscribe = subscribeBinaryFrames((buf: ArrayBuffer) => {
      const w = workerRef.current;
      if (!w || buf.byteLength < 2) return;

      const view      = new DataView(buf);
      const frameType = view.getUint8(0);
      if (frameType !== 0x10 && frameType !== 0x11) return;

      const cur = serialRef.current;
      if (!cur) return;

      const slen = view.getUint8(1);
      if (buf.byteLength < 2 + slen + 4) return;
      if (slen !== cur.length) return;
      const serialBytes = new Uint8Array(buf, 2, slen);
      for (let i = 0; i < slen; i++) {
        if (serialBytes[i] !== cur.charCodeAt(i)) return;
      }

      const doff = 2 + slen + 4; // skip serial + w/h

      if (frameType === 0x10) {
        if (buf.byteLength < doff + 2) return;
        const avcc = new Uint8Array(buf, doff + 1).slice(); // skip flags byte; copy → transferable
        if (avcc.length < 4) return;
        w.postMessage({ type: 'config', avcc: avcc.buffer }, [avcc.buffer]);
        return;
      }

      if (frameType === 0x11) {
        if (buf.byteLength < doff + 9) return;
        const isKey     = view.getUint8(doff) !== 0;
        const ptsHi     = view.getUint32(doff + 1, false);
        const ptsLo     = view.getUint32(doff + 5, false);
        const ptsUs     = ptsHi * 4_294_967_296 + ptsLo;
        const frameData = new Uint8Array(buf, doff + 9).slice(); // copy → transferable
        if (frameData.length === 0) return;
        w.postMessage(
          { type: 'frame', isKey, ptsUs, frameData: frameData.buffer },
          [frameData.buffer],
        );
      }
    });

    return () => {
      unsubscribe();
      worker.postMessage({ type: 'reset' });
      worker.terminate();
      workerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Reset when serial changes, then immediately replay cached config+IDR ──
  // Without replay, the worker sits with decoder=null until the next live IDR
  // (3-14 s depending on device). With replay, it decodes within ~50 ms.
  useEffect(() => {
    const w = workerRef.current;
    if (!w) return;

    w.postMessage({ type: 'reset' });
    if (!serial) return;

    // Replay config (SPS/PPS)
    const cfgBuf = getLastConfigFrame(serial);
    if (cfgBuf) {
      const view = new DataView(cfgBuf);
      const slen = view.getUint8(1);
      const doff = 2 + slen + 4;
      if (cfgBuf.byteLength >= doff + 2) {
        const avcc = new Uint8Array(cfgBuf, doff + 1).slice();
        if (avcc.length >= 4) {
          w.postMessage({ type: 'config', avcc: avcc.buffer }, [avcc.buffer]);
        }
      }
    }

    // Replay last keyframe — live P-frames after this IDR remain valid refs
    const keyBuf = getLastKeyFrame(serial);
    if (keyBuf) {
      const view = new DataView(keyBuf);
      const slen = view.getUint8(1);
      const doff = 2 + slen + 4;
      if (keyBuf.byteLength >= doff + 9) {
        const isKey     = view.getUint8(doff) !== 0;
        const ptsHi     = view.getUint32(doff + 1, false);
        const ptsLo     = view.getUint32(doff + 5, false);
        const ptsUs     = ptsHi * 4_294_967_296 + ptsLo;
        const frameData = new Uint8Array(keyBuf, doff + 9).slice();
        if (frameData.length > 0 && isKey) {
          w.postMessage(
            { type: 'frame', isKey: true, ptsUs, frameData: frameData.buffer },
            [frameData.buffer],
          );
        }
      }
    }
  }, [serial]);
}
