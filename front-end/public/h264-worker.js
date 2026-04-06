'use strict';
console.log('[H264Worker] LOADED v10');
/**
 * H264 VideoDecoder — Web Worker + OffscreenCanvas, zero-buffering.
 *
 * Strategy:
 *   1. Try hardware decode (prefer-hardware) — fast, low-latency.
 *   2. On async error → flag hardware as broken, reinit with software (no-preference).
 *   3. P-frames dropped if decodeQueueSize > 1 (keep at most 1 frame of latency).
 */

let decoder       = null;
let ctx           = null;
let waitIdr       = true;
let lastAvcc      = null;   // Uint8Array — last AVCDecoderConfigurationRecord
let hwFailed      = false;  // once hardware decode fails, stay on software

// ── helpers ────────────────────────────────────────────────────────────────

function getCodecString(avcc) {
  if (avcc.length < 4) return 'avc1.42E01E';
  return 'avc1.'
    + avcc[1].toString(16).padStart(2, '0')
    + avcc[2].toString(16).padStart(2, '0')
    + avcc[3].toString(16).padStart(2, '0');
}

function closeDecoder() {
  if (decoder) { try { decoder.close(); } catch (_) {} }
  decoder = null;
  waitIdr = true;
}

/** Strip inline SPS/PPS NALs (type 7/8) from AVCC frame data. */
function stripParamNals(avccBuf) {
  var src = new Uint8Array(avccBuf);
  var hasParams = false;
  for (var i = 0; i + 4 <= src.length;) {
    var len = ((src[i] << 24) | (src[i+1] << 16) | (src[i+2] << 8) | src[i+3]) >>> 0;
    if (i + 4 + len > src.length) break;
    var t = src[i + 4] & 0x1f;
    if (t === 7 || t === 8) { hasParams = true; break; }
    i += 4 + len;
  }
  if (!hasParams) return avccBuf;
  var out = new Uint8Array(src.length);
  var outPos = 0;
  for (var i = 0; i + 4 <= src.length;) {
    var len = ((src[i] << 24) | (src[i+1] << 16) | (src[i+2] << 8) | src[i+3]) >>> 0;
    if (i + 4 + len > src.length) break;
    var t = src[i + 4] & 0x1f;
    if (t !== 7 && t !== 8) { out.set(src.subarray(i, i + 4 + len), outPos); outPos += 4 + len; }
    i += 4 + len;
  }
  return out.buffer.slice(0, outPos);
}

function initDecoder(avccRecord) {
  closeDecoder();

  var codec = getCodecString(avccRecord);
  var desc  = avccRecord instanceof Uint8Array ? avccRecord : new Uint8Array(avccRecord);
  var accel = hwFailed ? 'no-preference' : 'prefer-hardware';

  decoder = new VideoDecoder({
    output: function(frame) {
      if (ctx) {
        if (ctx.canvas.width !== frame.displayWidth || ctx.canvas.height !== frame.displayHeight) {
          ctx.canvas.width  = frame.displayWidth;
          ctx.canvas.height = frame.displayHeight;
        }
        ctx.drawImage(frame, 0, 0);
      }
      frame.close();
      self.postMessage({ type: 'fps' });
    },
    error: function(e) {
      var msg = (e && e.message) ? e.message : String(e);
      console.error('[H264Worker] decoder error (accel=' + accel + '):', msg);
      if (!hwFailed) {
        // Hardware decode failed — switch to software for all future IDRs
        hwFailed = true;
        console.log('[H264Worker] switching to software decode');
      }
      closeDecoder();
      // Reinit immediately with software if we have config — next IDR will use it
    },
  });

  try {
    decoder.configure({ codec: codec, description: desc, hardwareAcceleration: accel });
    console.log('[H264Worker] configured accel=' + accel + ' codec=' + codec);
  } catch (e) {
    console.error('[H264Worker] configure failed:', e && e.message);
    if (!hwFailed) {
      // Synchronous failure on hardware — retry with software immediately
      hwFailed = true;
      decoder = null;
      initDecoder(avccRecord);
    } else {
      closeDecoder();
    }
  }
}

// ── message handler ────────────────────────────────────────────────────────

self.onmessage = function(event) {
  var data = event.data;

  switch (data.type) {

    case 'init':
      ctx = data.canvas.getContext('2d');
      console.log('[H264Worker] canvas ready');
      break;

    case 'config': {
      var avcc = new Uint8Array(data.avcc);
      if (avcc.length < 4) break;
      lastAvcc = avcc;
      console.log('[H264Worker] config len=' + avcc.length + ' codec=' + getCodecString(avcc));
      initDecoder(avcc);
      console.log('[H264Worker] decoder state=' + (decoder ? decoder.state : 'null'));
      break;
    }

    case 'frame': {
      if (!decoder) {
        if (!data.isKey || !lastAvcc) return;
        initDecoder(lastAvcc);
        if (!decoder) return;
      }
      if (decoder.state === 'closed') { closeDecoder(); return; }

      if (waitIdr) {
        if (!data.isKey) return;
        waitIdr = false;
        console.log('[H264Worker] first IDR decoded');
      }

      // Drop P-frames only when decoder queue is severely backed up (>6 frames ≈ 200ms at 30fps).
      // A tight threshold (>3) caused near-continuous drops during brief backpressure spikes
      // (hardware decode startup, post-IDR decode burst), freezing the screen until the next IDR.
      // With relay bitrate lowered to 2Mbps, IDR frames are small (~33KB) and transfer quickly,
      // so large queue buildups are rare — threshold 6 catches genuine overload without false positives.
      if (!data.isKey && decoder.decodeQueueSize > 6) return;

      var frameData = data.isKey ? stripParamNals(data.frameData) : data.frameData;
      if (frameData.byteLength === 0) return;

      try {
        decoder.decode(new EncodedVideoChunk({
          type     : data.isKey ? 'key' : 'delta',
          timestamp: data.ptsUs,
          data     : frameData,
        }));
      } catch (e) {
        console.error('[H264Worker] decode threw:', e && e.message);
        closeDecoder();
      }
      break;
    }

    case 'reset':
      // Keep lastAvcc so the next keyframe can reinit the decoder immediately
      // without waiting for a new config frame (which may arrive seconds later).
      closeDecoder();
      break;
  }
};
