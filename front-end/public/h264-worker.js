'use strict';
const H264_WORKER_DEBUG = false;
function debugLog() {
  if (H264_WORKER_DEBUG) console.log.apply(console, arguments);
}
debugLog('[H264Worker] LOADED v47');
/**
 * H264 VideoDecoder — Web Worker, push-model rendering.
 *
 * Strategy:
 *   1. prefer-hardware first — fast, low-latency.
 *   2. On async error → reinit with browser-selected acceleration until reset.
 *   3. Push frame to main thread immediately on decode output.
 *   4. Drop delta frames only when queue/latency crosses thresholds.
 */

let decoder = null;
let decoderAccel = '';
let waitIdr = true;
let lastAvcc = null; // Uint8Array — last AVCDecoderConfigurationRecord
let hwFailed = false; // skip forced hardware until an explicit recovery reset
let droppedDelta = 0;
let decodedFrames = 0;
let t0Us = 0; // local monotonic origin for chunk timestamps
let lastTsUs = 0; // strictly increasing chunk timestamp guard
let lastDecodeTsUs = 0; // timestamp of last chunk accepted by decoder
let pendingFrame = null; // latest frame waiting to be sent (VideoFrame path)
let frameInFlight = false; // one frame has been sent but not consumed by main
let lastOutputMs = 0;
let decodeFps = 15;
let targetFps = 15; // updated via 'set-target-fps'
let flushInFlight = false;
let needKeyframe = false;
const MAX_DRIFT_US = 500000;
const MAX_SAFE_TS_US = Number.MAX_SAFE_INTEGER;
let lastDecoderErrorLogAt = 0;
let sameDecoderErrorCount = 0;
let lastDecoderErrorMsg = '';
let lastChunkDebug = null;
let decoderInitToken = 0;
let decoderConfiguring = false;
let pendingKeyChunk = null;
let lastBackpressurePostAt = 0;
let renderCanvas = null;
let renderCtx = null;

// Keep the stream live-first. Once WebCodecs has this much pending decode work,
// decoding more P-frames only makes the visible stream play old frames in bursts.
// Drop deltas, request a fresh IDR from the main thread, and resume from that IDR.
const DELTA_DROP_QUEUE_SIZE = 3;
const KEY_RESET_QUEUE_SIZE = 6;

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
  if (now - lastDecoderErrorLogAt < 1500 && sameDecoderErrorCount > 0) return;
  lastDecoderErrorLogAt = now;
  console.warn(
    '[H264Worker] decoder error (accel=' +
      accel +
      ')' +
      (sameDecoderErrorCount > 0 ? ' x' + (sameDecoderErrorCount + 1) : '') +
      ':',
    text
  );
  if (lastChunkDebug)
    console.warn('[H264Worker] last chunk:', formatChunkDebug(lastChunkDebug));
}

function postDecoderError(accel, msg) {
  self.postMessage({
    type: 'decoder-error',
    accel: String(accel || ''),
    message: String(msg || 'unknown')
  });
}

function postBackpressure(reason) {
  var now = Date.now();
  if (now - lastBackpressurePostAt < 500) return;
  lastBackpressurePostAt = now;
  self.postMessage({
    type: 'decoder-backpressure',
    reason: String(reason || 'decode_queue'),
    decodeQueueSize: decoder ? decoder.decodeQueueSize || 0 : 0,
    droppedDelta
  });
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
  return (
    'avc1.' +
    avcc[1].toString(16).padStart(2, '0') +
    avcc[2].toString(16).padStart(2, '0') +
    avcc[3].toString(16).padStart(2, '0')
  );
}

function closeDecoder() {
  if (decoder) {
    try {
      decoder.close();
    } catch (_) {}
  }
  decoder = null;
  decoderAccel = '';
  waitIdr = true;
  lastDecodeTsUs = 0;
  lastTsUs = 0;
  t0Us = 0;
  if (pendingFrame) {
    try {
      pendingFrame.close();
    } catch (_) {}
    pendingFrame = null;
  }
  frameInFlight = false;
  lastOutputMs = 0;
  decodeFps = targetFps;
  flushInFlight = false;
  needKeyframe = false;
}

function fallbackFromHardwareDecodeError(accel) {
  if (accel !== 'prefer-hardware') return false;
  hwFailed = true;
  closeDecoder();
  if (!lastAvcc) return false;
  console.warn(
    '[H264Worker] hardware decode failed; using fallback acceleration'
  );
  self.postMessage({ type: 'hardware-fallback' });
  initDecoder(lastAvcc);
  postBackpressure('hardware_decode_fallback');
  return true;
}

function tryPostPendingFrame() {
  if (frameInFlight || !pendingFrame) return;
  var frame = pendingFrame;
  pendingFrame = null;
  if (tryRenderFrameInWorker(frame)) return;
  frameInFlight = true;
  self.postMessage(
    {
      type: 'frame',
      frame: frame,
      width: frame.displayWidth,
      height: frame.displayHeight
    },
    [frame]
  );
}

function attachCanvas(canvas) {
  renderCanvas = canvas || null;
  renderCtx = null;
  if (!renderCanvas || typeof renderCanvas.getContext !== 'function') return;
  try {
    renderCtx = renderCanvas.getContext('2d', {
      alpha: false,
      desynchronized: true
    });
  } catch (_) {
    renderCtx = null;
  }
}

function tryRenderFrameInWorker(frame) {
  if (!renderCanvas || !renderCtx || !frame) return false;
  try {
    var width = Math.max(1, Math.floor(frame.displayWidth || 1));
    var height = Math.max(1, Math.floor(frame.displayHeight || 1));
    if (renderCanvas.width !== width) renderCanvas.width = width;
    if (renderCanvas.height !== height) renderCanvas.height = height;
    renderCtx.drawImage(frame, 0, 0, width, height);
    self.postMessage({
      type: 'frame-rendered',
      width: width,
      height: height
    });
    return true;
  } catch (e) {
    postBackpressure('worker_canvas_render_failed');
    return true;
  } finally {
    try {
      frame.close();
    } catch (_) {}
  }
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
    if (lastTsUs > 0 && tsUs - lastTsUs > MAX_DRIFT_US) {
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

function toHexPrefix(src, limit) {
  var out = [];
  var n = Math.min(src.length, limit || 16);
  for (var i = 0; i < n; i++) out.push(src[i].toString(16).padStart(2, '0'));
  return out.join('');
}

function parseAvcc(src, collectTypes) {
  var types = collectTypes ? [] : null;
  var nalCount = 0;
  var valid = src.length > 0;
  var hasIdr = false;
  for (var i = 0; i + 4 <= src.length; ) {
    var len =
      ((src[i] << 24) | (src[i + 1] << 16) | (src[i + 2] << 8) | src[i + 3]) >>>
      0;
    if (len === 0 || i + 4 + len > src.length) {
      valid = false;
      break;
    }
    var nalHeader = src[i + 4];
    if ((nalHeader & 0x80) !== 0) {
      valid = false;
      break;
    }
    var t = nalHeader & 0x1f;
    if (types) types.push(t + ':' + len);
    nalCount += 1;
    if (t === 5 && len > 1) hasIdr = true;
    i += 4 + len;
  }
  if (i !== src.length || nalCount === 0) valid = false;
  return { valid: valid, hasIdr: valid && hasIdr, types: types };
}

function normalizeFrameData(frameData) {
  var src =
    frameData instanceof Uint8Array ? frameData : new Uint8Array(frameData);
  return {
    data: src,
    parsed: parseAvcc(src),
    source: src,
    converted: false
  };
}

function formatChunkDebug(chunk) {
  var parsed = parseAvcc(chunk.data, true);
  return (
    'wireKey=' +
    chunk.wireKey +
    ' pts=' +
    chunk.ptsUs +
    ' len=' +
    chunk.source.length +
    ' converted=' +
    chunk.converted +
    ' valid=' +
    parsed.valid +
    ' idr=' +
    parsed.hasIdr +
    ' nals=' +
    parsed.types.join(',') +
    ' hex=' +
    toHexPrefix(chunk.source, 20)
  );
}

function initDecoder(avccRecord, keyChunk) {
  closeDecoder();

  var codec = getCodecString(avccRecord);
  var desc =
    avccRecord instanceof Uint8Array ? avccRecord : new Uint8Array(avccRecord);
  var token = ++decoderInitToken;
  decoderConfiguring = true;
  pendingKeyChunk = keyChunk || null;

  configureSupportedDecoder(token, codec, desc);
}

function bytesEqual(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

function shouldReconfigureDecoder(nextAvcc, configChanged) {
  if (configChanged) return true;
  if (!lastAvcc) return true;
  if (!bytesEqual(lastAvcc, nextAvcc)) return true;
  if (decoder && decoder.state !== 'closed') return false;
  return !decoderConfiguring;
}

function createDecoder(accel) {
  return new VideoDecoder({
    output: function (frame) {
      var now = performance.now();
      if (lastOutputMs > 0) {
        var dt = now - lastOutputMs;
        if (dt > 0) {
          var instFps = 1000 / dt;
          // Smooth decode throughput estimate to avoid noisy oscillations.
          decodeFps = decodeFps * 0.85 + instFps * 0.15;
        }
      }
      lastOutputMs = now;
      decodedFrames++;
      // Keep latest decoded frame only.
      if (pendingFrame) {
        var prevTs =
          typeof pendingFrame.timestamp === 'number'
            ? pendingFrame.timestamp
            : -1;
        var nextTs = typeof frame.timestamp === 'number' ? frame.timestamp : -1;
        if (nextTs >= 0 && prevTs >= 0 && nextTs <= prevTs) {
          try {
            frame.close();
          } catch (_) {}
          return;
        }
        try {
          pendingFrame.close();
        } catch (_) {}
      }
      pendingFrame = frame;
      // Push: send immediately if slot free; pull-frame in RAF is fallback.
      tryPostPendingFrame();
      if ((decodedFrames & 15) === 0) {
        self.postMessage({ type: 'fps' });
      }
      if ((decodedFrames & 31) === 0 && decoder) {
        self.postMessage({
          type: 'stats',
          decodeQueueSize: decoder.decodeQueueSize || 0,
          droppedDelta,
          decodedFrames,
          accel: accel
        });
      }
    },
    error: function (e) {
      var msg = e && e.message ? e.message : String(e);
      logDecoderError(accel, msg);
      if (fallbackFromHardwareDecodeError(accel)) return;
      postDecoderError(accel, msg);
      closeDecoder();
    }
  });
}

async function configureSupportedDecoder(token, codec, desc) {
  var candidates = [];
  if (!hwFailed) {
    candidates.push({
      codec: codec,
      description: desc,
      hardwareAcceleration: 'prefer-hardware',
      optimizeForLatency: true
    });
  }
  candidates.push(
    {
      codec: codec,
      description: desc,
      hardwareAcceleration: 'prefer-software',
      optimizeForLatency: true
    },
    {
      codec: codec,
      description: desc,
      hardwareAcceleration: 'no-preference',
      optimizeForLatency: true
    },
    {
      codec: codec,
      description: desc,
      optimizeForLatency: true
    }
  );

  for (var i = 0; i < candidates.length; i++) {
    var cfg = candidates[i];
    try {
      if (typeof VideoDecoder.isConfigSupported === 'function') {
        var support = await VideoDecoder.isConfigSupported(cfg);
        if (token !== decoderInitToken) return;
        if (!support || support.supported === false) continue;
        cfg = support.config || cfg;
      }
      var accel = cfg.hardwareAcceleration || 'no-preference';
      decoder = createDecoder(accel);
      decoder.configure(cfg);
      decoderAccel = accel;
      decoderConfiguring = false;
      waitIdr = true;
      debugLog('[H264Worker] configured accel=' + accel + ' codec=' + codec);
      if (pendingKeyChunk) {
        var pending = pendingKeyChunk;
        pendingKeyChunk = null;
        decodeChunk(pending.isKey, pending.ptsUs, pending.frameData);
      }
      return;
    } catch (e) {
      if (decoder) {
        try {
          decoder.close();
        } catch (_) {}
      }
      decoder = null;
      if (cfg.hardwareAcceleration === 'prefer-hardware' && !hwFailed) {
        hwFailed = true;
        self.postMessage({ type: 'hardware-fallback' });
      }
      console.warn(
        '[H264Worker] config candidate rejected:',
        codec,
        cfg.hardwareAcceleration || 'default',
        e && e.message
      );
    }
  }
  decoderConfiguring = false;
  pendingKeyChunk = null;
  var msg = 'no supported WebCodecs config for codec=' + codec;
  console.error('[H264Worker] ' + msg);
  postDecoderError('config', msg);
}

function decodeChunk(isKey, ptsUs, frameData) {
  var normalized = normalizeFrameData(frameData);
  var data = normalized.data;
  lastChunkDebug = {
    wireKey: Boolean(isKey),
    ptsUs: ptsUs,
    data: data,
    source: normalized.source,
    converted: normalized.converted
  };
  if (!normalized.parsed.valid) {
    postBackpressure('invalid_h264_payload');
    return;
  }
  // Protocol is_key can lie in both directions (stale cache can mark a P-frame
  // as key; relay can miss an IDR when SPS/PPS/AUD precede the slice). WebCodecs
  // needs EncodedVideoChunk.type to match the real IDR presence.
  var realKey = normalized.parsed.hasIdr;
  if (isKey && !realKey) {
    postBackpressure('false_keyframe');
  } else if (!isKey && realKey) {
    postBackpressure('missed_keyframe_flag');
  }

  if (decoderConfiguring) {
    if (realKey)
      pendingKeyChunk = { isKey: true, ptsUs: ptsUs, frameData: frameData };
    return;
  }
  if (!decoder) {
    if (!realKey || !lastAvcc) return;
    initDecoder(lastAvcc, {
      isKey: true,
      ptsUs: ptsUs,
      frameData: frameData
    });
    return;
  }
  if (decoder.state === 'closed') {
    closeDecoder();
    return;
  }

  var decodeQueueSize = decoder.decodeQueueSize || 0;
  if (!realKey && decodeQueueSize >= DELTA_DROP_QUEUE_SIZE) {
    droppedDelta++;
    waitIdr = true;
    postBackpressure('decode_queue_delta_drop');
    return;
  }
  if (realKey && decodeQueueSize >= KEY_RESET_QUEUE_SIZE && lastAvcc) {
    // A fresh IDR is more valuable than draining stale queued deltas. Resetting
    // drops browser-side backlog and starts the decoder from the newest keyframe.
    initDecoder(lastAvcc, {
      isKey: true,
      ptsUs: ptsUs,
      frameData: frameData
    });
    postBackpressure('decode_queue_key_reset');
    return;
  }

  if (waitIdr) {
    if (!realKey) return;
    waitIdr = false;
    debugLog('[H264Worker] first IDR decoded');
  }
  if (realKey) {
    needKeyframe = false;
  }

  var tsUs = normalizeChunkTimestampUs(ptsUs);
  if (data.byteLength === 0) return;

  try {
    decoder.decode(
      new EncodedVideoChunk({
        type: realKey ? 'key' : 'delta',
        timestamp: tsUs,
        data: data
      })
    );
    lastDecodeTsUs = tsUs;
  } catch (e) {
    var accel =
      decoderAccel || (hwFailed ? 'no-preference' : 'prefer-hardware');
    var msg = e && e.message;
    logDecoderError(accel, msg);
    if (fallbackFromHardwareDecodeError(accel)) return;
    postDecoderError(accel, msg);
    closeDecoder();
  }
}

// ── message handler ────────────────────────────────────────────────────────

self.onmessage = function (event) {
  var data = event.data;

  switch (data.type) {
    case 'init':
      debugLog('[H264Worker] init');
      if (data.preferHardware === false) hwFailed = true;
      break;

    case 'attach-canvas':
      attachCanvas(data.canvas);
      tryPostPendingFrame();
      break;

    case 'config': {
      var avcc = new Uint8Array(data.avcc);
      if (avcc.length < 4) break;
      var reconfigure = shouldReconfigureDecoder(avcc, false);
      lastAvcc = new Uint8Array(avcc);
      debugLog(
        '[H264Worker] config len=' +
          avcc.length +
          ' codec=' +
          getCodecString(avcc)
      );
      if (reconfigure) initDecoder(lastAvcc);
      debugLog(
        '[H264Worker] decoder state=' + (decoder ? decoder.state : 'null')
      );
      break;
    }

    case 'frame': {
      decodeChunk(Boolean(data.isKey), Number(data.ptsUs || 0), data.frameData);
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
        var flags = view.getUint8(doff);
        var avcc = new Uint8Array(buf, doff + 1).slice(); // skip flags byte
        if (avcc.length < 4) return;
        var configChanged = (flags & 0x01) !== 0;
        var reconfigure = shouldReconfigureDecoder(avcc, configChanged);
        lastAvcc = avcc;
        if (reconfigure) initDecoder(lastAvcc);
        return;
      }

      if (frameType === 0x11) {
        if (buf.byteLength < doff + 9) return;
        var isKey = view.getUint8(doff) !== 0;
        var ptsHi = view.getUint32(doff + 1, false);
        var ptsLo = view.getUint32(doff + 5, false);
        var ptsBig = (BigInt(ptsHi) << 32n) | BigInt(ptsLo);
        var ptsUs = 0;
        if (ptsBig > 0n && ptsBig <= BigInt(MAX_SAFE_TS_US)) {
          ptsUs = Number(ptsBig);
        }

        var rawFrame = new Uint8Array(buf, doff + 9);
        if (rawFrame.byteLength === 0) return;
        decodeChunk(isKey, ptsUs, rawFrame);
      }
      break;
    }

    case 'reset':
      // Keep lastAvcc so the next keyframe can reinit the decoder immediately
      // without waiting for a new config frame (which may arrive seconds later).
      if (data.retryHardware !== false) hwFailed = false;
      decoderInitToken++;
      decoderConfiguring = false;
      pendingKeyChunk = null;
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
