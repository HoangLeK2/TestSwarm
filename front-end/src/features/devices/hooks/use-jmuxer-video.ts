'use client';

/**
 * useJMuxerVideo — H264 live decode via jmuxer (MSE / SourceBuffer).
 *
 * Key insight: Android H264 encoder ALWAYS embeds SPS+PPS inline inside IDR
 * frames (Annex-B order: SPS NAL → PPS NAL → IDR slice NAL).  Do NOT prepend
 * extra SPS+PPS from the config frame — that creates duplicate parameter sets
 * which cause an MSE error and instant black screen.
 *
 * Timing note: jmuxer (and therefore the binary listener) are set up
 * synchronously in the effect.  ws.ts replays the cached config + last
 * keyframe via queueMicrotask so they land right after the effect returns —
 * no frame is ever missed.
 */

import { useEffect, useRef } from 'react';
import JMuxer from 'jmuxer';
import { subscribeBinaryFrames } from '../services/ws';

// ── helpers ──────────────────────────────────────────────────────────────────

/**
 * Convert AVCC-format buffer (4-byte big-endian length-prefixed NALs)
 * → Annex-B (0x00000001 start-code prefixed NALs).
 */
function avccToAnnexB(buf: ArrayBuffer, byteOffset: number, byteLength: number): Uint8Array {
  const src = new Uint8Array(buf, byteOffset, byteLength);
  const out = new Uint8Array(byteLength);
  let i = 0, outPos = 0;
  while (i + 4 <= src.length) {
    const len = ((src[i] << 24) | (src[i + 1] << 16) | (src[i + 2] << 8) | src[i + 3]) >>> 0;
    if (i + 4 + len > src.length) break;
    out[outPos]     = 0x00; out[outPos + 1] = 0x00;
    out[outPos + 2] = 0x00; out[outPos + 3] = 0x01;
    outPos += 4;
    out.set(src.subarray(i + 4, i + 4 + len), outPos);
    outPos += len;
    i += 4 + len;
  }
  return out.subarray(0, outPos);
}

// ── hook ──────────────────────────────────────────────────────────────────────

export function useJMuxerVideo(
  serial: string,
  videoRef: React.RefObject<HTMLVideoElement | null>,
  opts?: { onFrame?: () => void }
) {
  const jmuxerRef  = useRef<JMuxer | null>(null);
  const serialRef  = useRef(serial);
  const onFrameRef = useRef(opts?.onFrame);

  serialRef.current  = serial;
  onFrameRef.current = opts?.onFrame;

  // ── Lifecycle: create jmuxer once, subscribe to WS binary frames ──────────
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const video = videoRef.current;
    if (!video) return;

    // Keep video playing — browser may pause on certain events
    const onPause = () => { video.play().catch(() => {}); };
    video.addEventListener('pause', onPause);

    let jmuxer: JMuxer | null = null;
    try {
      jmuxer = new JMuxer({
        node: video,
        mode: 'video',
        flushingTime: 0,
        fps: 30,
        debug: false,
        onReady() { console.log('[JMuxer] MSE ready'); },
        onError(data: unknown) {
          console.warn('[JMuxer] MSE error, resetting:', data);
          try { jmuxer?.reset(); } catch {}
        },
      });
      jmuxerRef.current = jmuxer;
    } catch (e) {
      console.error('[JMuxer] init failed:', e);
      video.removeEventListener('pause', onPause);
      return;
    }

    const unsubscribe = subscribeBinaryFrames((buf: ArrayBuffer) => {
      if (!jmuxer) return;
      if (buf.byteLength < 2) return;

      const view      = new DataView(buf);
      const frameType = view.getUint8(0);
      if (frameType !== 0x11) return; // only video frames; config handled by ws.ts cache

      const cur = serialRef.current;
      if (!cur) return;

      const slen = view.getUint8(1);
      if (buf.byteLength < 2 + slen + 4) return;
      if (slen !== cur.length) return;

      const serialBytes = new Uint8Array(buf, 2, slen);
      for (let i = 0; i < slen; i++) {
        if (serialBytes[i] !== cur.charCodeAt(i)) return;
      }

      const doff    = 2 + slen + 4; // skip serial + w/h
      if (buf.byteLength < doff + 9) return;

      const avccOff = doff + 9; // skip is_key (1) + pts (8)
      const avccLen = buf.byteLength - avccOff;
      if (avccLen <= 0) return;

      // Convert AVCC → Annex-B and feed.
      // Android encoder embeds SPS+PPS inline in IDR frames so jmuxer initialises
      // the SourceBuffer from the first IDR without any manual SPS/PPS injection.
      const annexb = avccToAnnexB(buf, avccOff, avccLen);
      if (annexb.length === 0) return;

      try {
        jmuxer.feed({ video: annexb });
      } catch (e) {
        console.warn('[JMuxer] feed threw:', e);
        try { jmuxer?.reset(); } catch {}
      }
      onFrameRef.current?.();
    });

    return () => {
      video.removeEventListener('pause', onPause);
      unsubscribe();
      try { jmuxer?.destroy(); } catch {}
      jmuxerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Reset decoder when serial changes ────────────────────────────────────
  // ws.ts will replay cached config + keyframe via queueMicrotask so the
  // decoder gets an IDR shortly after reset without waiting 14 s.
  useEffect(() => {
    const jmuxer = jmuxerRef.current;
    if (!jmuxer) return;
    try { jmuxer.reset(); } catch {}
  }, [serial]);
}
