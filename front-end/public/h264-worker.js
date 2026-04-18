'use strict';
console.log('[H264Worker] LOADED v18');
/**
 * H264 VideoDecoder — Web Worker + OffscreenCanvas, zero-buffering.
 *
 * Strategy:
 *   1. Try hardware decode (prefer-hardware) — fast, low-latency.
 *   2. On async error → flag hardware as broken, reinit with software (no-preference).
 *   3. Low-latency mode: drop delta frames only when queue/latency crosses thresholds.
 *      This favors freshness over completeness (less "khung khung"/rubber-band lag).
 */

let decoder       = null;
let waitIdr       = true;
let lastAvcc      = null;   // Uint8Array — last AVCDecoderConfigurationRecord
let hwFailed      = false;  // once hardware decode fails, stay on software
let droppedDelta  = 0;
let decodedFrames = 0;
let t0Us          = 0;      // local monotonic origin for chunk timestamps
let lastTsUs      = 0;      // strictly increasing chunk timestamp guard
let lastDecodeTsUs = 0;     // timestamp of last chunk accepted by decoder
let pendingFrame = null;    // latest frame waiting to be sent
let frameInFlight = false;  // one frame has been sent but not consumed by main
let lastOutputMs = 0;
let decodeFps = 15;
let targetFps = 15;  // default matches config.yaml scrcpy_max_fps; updated via 'set-target-fps'
let flushInFlight = false;
let needKeyframe = false;
const MAX_DRIFT_US = 500000;
const MAX_SAFE_TS_US = Number.MAX_SAFE_INTEGER;
let lastDecoderErrorLogAt = 0;
let sameDecoderErrorCount = 0;
let lastDecoderErrorMsg = '';

function logDecoderError(accel, msg) {
  var now = Date.now();
  var text = String(msg || 'unknown');
  if (text === lastDecoderErrorMsg) {
    sameDecoderErrorCount += 1;
  } else {
    lastDecoderErrorMsg = text;
    sameDecoderErrorCount = 0;
  }
  // throttle noisy decode failures (device stream hiccups can spam thousands of lines)
  if ((now - lastDecoderErrorLogAt) < 1500 && sameDecoderErrorCount > 0) return;
  lastDecoderErrorLogAt = now;
  console.error(
    '[H264Worker] decoder error (accel=' + accel + ')'
      + (sameDecoderErrorCount > 0 ? ' x' + (sameDecoderErrorCount + 1) : '')
      + ':',
    text
  );
}

function nextMonotonicTsUs() {
  var nowUs = Math.floor(performance.now() * 1000);
  if (t0Us === 0) t0Us = nowUs;
  var ts = nowUs - t0Us;
  // WebCodecs expects monotonically increasing timestamps.
  if (ts <= lastTsUs) ts = lastTsUs + 1000; // +1ms safety step
  lastTsUs = ts;
  return ts;
}

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
  lastDecodeTsUs = 0;
  lastTsUs = 0;
  t0Us = 0;
  if (pendingFrame) {
    try { pendingFrame.close(); } catch (_) {}
    pendingFrame = null;
  }
  frameInFlight = false;
  lastOutputMs = 0;
  decodeFps = targetFps;
  flushInFlight = false;
  needKeyframe = false;
}

function tryPostPendingFrame() {
  if (frameInFlight || !pendingFrame) return;
  var frame = pendingFrame;
  pendingFrame = null;
  frameInFlight = true;
  self.postMessage(
    {
      type: 'frame',
      frame: frame,
      width: frame.displayWidth,
      height: frame.displayHeight,
    },
    [frame]
  );
}

function normalizeChunkTimestampUs(ptsUs) {
  var tsUs = 0;
  if (
    typeof ptsUs === 'number' &&
    Number.isFinite(ptsUs) &&
    ptsUs > 0 &&
    ptsUs <= MAX_SAFE_TS_US
  ) {
    tsUs = Math.floor(ptsUs);
    if (lastTsUs > 0 && (tsUs - lastTsUs) > MAX_DRIFT_US) {
      tsUs = lastTsUs + 1000;
    }
    // Guard against non-monotonic source PTS.
    if (tsUs <= lastTsUs) tsUs = lastTsUs + 1000;
  } else {
    tsUs = nextMonotonicTsUs();
    if (tsUs <= lastTsUs) tsUs = lastTsUs + 1000;
  }
  lastTsUs = tsUs;
  return tsUs;
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
      var now = performance.now();
      if (lastOutputMs > 0) {
        var dt = now - lastOutputMs;
        if (dt > 0) {
          var instFps = 1000 / dt;
          // Smooth decode throughput estimate to avoid noisy oscillations.
          decodeFps = (decodeFps * 0.85) + (instFps * 0.15);
        }
      }
      lastOutputMs = now;
      decodedFrames++;
      var targetFrameTimeMs = 1000 / Math.max(1, targetFps);
      var queueDelayMs = (decoder ? decoder.decodeQueueSize : 0) * targetFrameTimeMs;
      // Wider thresholds reduce "stutter by over-dropping" during touch gestures.
      var dynamicThresholdMs = Math.max(targetFrameTimeMs * 3, 360 - decodeFps * 4);
      // Use actual target FPS (not hardcoded 30) — at 15fps config, 30*0.55=16.5
      // would ALWAYS trigger overload since decode rate ≈ 15fps.
      var overload = decodeFps < (targetFps * 0.5);

      // Output-stage dropping policy (after decode):
      // keep decode pipeline intact, shed only presented frames when overloaded.
      if (queueDelayMs > dynamicThresholdMs || overload) {
        droppedDelta++;
        try { frame.close(); } catch (_) {}
        return;
      }

      // Keep latest decoded frame only.
      if (pendingFrame) {
        var prevTs = (typeof pendingFrame.timestamp === 'number') ? pendingFrame.timestamp : -1;
        var nextTs = (typeof frame.timestamp === 'number') ? frame.timestamp : -1;
        if (nextTs >= 0 && prevTs >= 0 && nextTs <= prevTs) {
          try { frame.close(); } catch (_) {}
          return;
        }
        try { pendingFrame.close(); } catch (_) {}
      }
      pendingFrame = frame;
      // Pull-model: main thread requests frame on RAF; worker does not push eagerly.
      if ((decodedFrames & 15) === 0) {
        self.postMessage({ type: 'fps' });
      }
      if ((decodedFrames & 31) === 0 && decoder) {
        self.postMessage({
          type: 'stats',
          decodeQueueSize: decoder.decodeQueueSize || 0,
          droppedDelta,
          decodedFrames,
          accel: hwFailed ? 'software' : 'hardware',
        });
      }
    },
    error: function(e) {
      var msg = (e && e.message) ? e.message : String(e);
      logDecoderError(accel, msg);
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
    // optimizeForLatency: true — instructs the decoder to output frames as soon as
    // they are decoded (no internal reorder buffer). Critical for 1-in-1-out behavior
    // with H264 Baseline profile streams from scrcpy. Without this, decoders may
    // buffer 4 frames after each IDR before emitting the first VideoFrame.
    decoder.configure({
      codec: codec,
      description: desc,
      hardwareAcceleration: accel,
      optimizeForLatency: true,
    });
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
      console.log('[H264Worker] init');
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
      if (data.isKey) {
        needKeyframe = false;
      }

      // Hybrid timestamping:
      // - prefer source PTS when available
      // - enforce strict monotonicity to avoid WebCodecs reorder glitches
      var tsUs = normalizeChunkTimestampUs(data.ptsUs);
      var frameData = data.frameData;
      if (data.isKey) {
        frameData = stripParamNals(data.frameData);
      }
      if (frameData.byteLength === 0) return;

      try {
        decoder.decode(new EncodedVideoChunk({
          type     : data.isKey ? 'key' : 'delta',
          // Use client monotonic clock to avoid remote PTS jitter/stalls.
          timestamp: tsUs,
          data     : frameData,
        }));
        lastDecodeTsUs = tsUs;
        // Do not flush in live mode.
        // flush() forces "next chunk must be keyframe", which creates
        // decode errors under normal P-frame flow.
      } catch (e) {
        logDecoderError(hwFailed ? 'no-preference' : 'prefer-hardware', e && e.message);
        closeDecoder();
      }
      break;
    }

    case 'binary': {
      var buf = data.buf;
      if (!(buf instanceof ArrayBuffer) || buf.byteLength < 2) return;
      var frameType = data.frameType;
      var view = new DataView(buf);
      var slen = view.getUint8(1);
      var doff = 2 + slen + 4; // skip serial + w/h

      if (frameType === 0x10) {
        if (buf.byteLength < doff + 2) return;
        var avcc = new Uint8Array(buf, doff + 1); // skip flags byte
        if (avcc.length < 4) return;
        lastAvcc = new Uint8Array(avcc);
        initDecoder(lastAvcc);
        return;
      }

      if (frameType === 0x11) {
        if (buf.byteLength < doff + 9) return;
        if (!decoder) {
          if (!lastAvcc) return;
          initDecoder(lastAvcc);
          if (!decoder) return;
        }
        if (decoder.state === 'closed') {
          closeDecoder();
          return;
        }
        var isKey = view.getUint8(doff) !== 0;
        var ptsHi = view.getUint32(doff + 1, false);
        var ptsLo = view.getUint32(doff + 5, false);
        var ptsBig = (BigInt(ptsHi) << 32n) | BigInt(ptsLo);
        var ptsUs = 0;
        if (ptsBig > 0n && ptsBig <= BigInt(MAX_SAFE_TS_US)) {
          ptsUs = Number(ptsBig);
        }

        if (waitIdr) {
          if (!isKey) return;
          waitIdr = false;
        }
        if (isKey) {
          needKeyframe = false;
        }

        var tsUs = normalizeChunkTimestampUs(ptsUs);
        var rawFrame = new Uint8Array(buf, doff + 9);
        if (rawFrame.byteLength === 0) return;
        var frameData = rawFrame;
        if (isKey) {
          frameData = new Uint8Array(stripParamNals(buf.slice(doff + 9)));
        }
        if (frameData.byteLength === 0) return;

        try {
          decoder.decode(new EncodedVideoChunk({
            type: isKey ? 'key' : 'delta',
            timestamp: tsUs,
            data: frameData,
          }));
          lastDecodeTsUs = tsUs;
          // Do not flush in live mode (see note above).
        } catch (e) {
          logDecoderError(hwFailed ? 'no-preference' : 'prefer-hardware', e && e.message);
          closeDecoder();
        }
      }
      break;
    }

    case 'reset':
      // Keep lastAvcc so the next keyframe can reinit the decoder immediately
      // without waiting for a new config frame (which may arrive seconds later).
      closeDecoder();
      break;

    case 'frame-consumed':
      frameInFlight = false;
      tryPostPendingFrame();
      break;

    case 'pull-frame':
      tryPostPendingFrame();
      break;

    case 'set-target-fps':
      if (typeof data.fps === 'number' && data.fps > 0) {
        targetFps = data.fps;
      }
      break;
  }
};
