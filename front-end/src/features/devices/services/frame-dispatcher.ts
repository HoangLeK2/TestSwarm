/**
 * frame-dispatcher.ts
 *
 * Global singleton that receives decoded binary frame messages from the WebSocket
 * and dispatches them directly to the subscribing DeviceScreen canvas — zero React
 * state updates, zero re-renders per frame.
 *
 * Binary frame protocol (server → browser):
 *
 *  JPEG (0x01):
 *    [0x01][serial_len:1B][serial:NB][width:2B BE][height:2B BE][jpeg_bytes]
 *
 *  H264 config / AVCDecoderConfigurationRecord (0x10):
 *    [0x10][serial_len:1B][serial:NB][width:2B BE][height:2B BE][avcc_config]
 *
 *  H264 video frame (0x11):
 *    [0x11][serial_len:1B][serial:NB][width:2B BE][height:2B BE]
 *         [is_key:1B][pts_hi:4B BE][pts_lo:4B BE][avcc_nal_units]
 */

export type FrameType = 'jpeg' | 'h264_config' | 'h264_key' | 'h264_delta';

export interface JpegFrame {
  type: 'jpeg';
  data: Uint8Array;
  width: number;
  height: number;
}

export interface H264ConfigFrame {
  type: 'h264_config';
  data: Uint8Array; // AVCDecoderConfigurationRecord
  width: number;
  height: number;
}

export interface H264VideoFrame {
  type: 'h264_key' | 'h264_delta';
  data: Uint8Array; // AVCC length-prefixed NAL units
  width: number;
  height: number;
  ptsUs: number;   // presentation timestamp in microseconds
}

export type FrameEvent = JpegFrame | H264ConfigFrame | H264VideoFrame;

type FrameHandler = (evt: FrameEvent) => void;

const _handlers = new Map<string, Set<FrameHandler>>();
const _latest   = new Map<string, FrameEvent>();

const _dec = new TextDecoder();

export const FrameDispatcher = {
  subscribe(serial: string, handler: FrameHandler): () => void {
    if (!_handlers.has(serial)) _handlers.set(serial, new Set());
    _handlers.get(serial)!.add(handler);
    // Immediately deliver last known frame so canvas shows something on mount
    const last = _latest.get(serial);
    if (last) try { handler(last); } catch {}
    return () => _handlers.get(serial)?.delete(handler);
  },

  dispatch(serial: string, evt: FrameEvent): void {
    _latest.set(serial, evt);
    const set = _handlers.get(serial);
    if (!set) return;
    for (const h of set) try { h(evt); } catch {}
  },

  /** Latest frame for a serial — used by recording flow for screenshot capture. */
  getLatest(serial: string): FrameEvent | null {
    return _latest.get(serial) ?? null;
  },

  /** Extract raw JPEG bytes from the latest frame for a serial (recording/screenshot). */
  getLatestJpeg(serial: string): Uint8Array | null {
    const f = _latest.get(serial);
    return f?.type === 'jpeg' ? f.data : null;
  },
};

// ─── Binary frame parser ────────────────────────────────────────────────────

export function parseBinaryFrame(
  buf: ArrayBuffer,
): { serial: string; evt: FrameEvent } | null {
  if (buf.byteLength < 6) return null;
  const view  = new DataView(buf);
  const type  = view.getUint8(0);
  const slen  = view.getUint8(1);
  if (buf.byteLength < 2 + slen + 4) return null;

  const serial = _dec.decode(new Uint8Array(buf, 2, slen));
  const base   = 2 + slen;
  const w      = view.getUint16(base,     false); // big-endian
  const h      = view.getUint16(base + 2, false);
  const dOff   = base + 4;

  // ── JPEG ──────────────────────────────────────────────────────────────────
  if (type === 0x01) {
    return {
      serial,
      evt: { type: 'jpeg', data: new Uint8Array(buf, dOff), width: w, height: h },
    };
  }

  // ── H264 config (AVCDecoderConfigurationRecord) ───────────────────────────
  if (type === 0x10) {
    return {
      serial,
      evt: { type: 'h264_config', data: new Uint8Array(buf, dOff), width: w, height: h },
    };
  }

  // ── H264 video frame ──────────────────────────────────────────────────────
  if (type === 0x11) {
    if (buf.byteLength < dOff + 9) return null;
    const isKey = view.getUint8(dOff) !== 0;
    // Reconstruct 64-bit PTS from two 32-bit halves (JS numbers are safe up to 2^53)
    const ptsUs = view.getUint32(dOff + 1, false) * 4_294_967_296 +
                  view.getUint32(dOff + 5, false);
    return {
      serial,
      evt: {
        type:  isKey ? 'h264_key' : 'h264_delta',
        data:  new Uint8Array(buf, dOff + 9),
        width: w, height: h, ptsUs,
      },
    };
  }

  return null;
}
