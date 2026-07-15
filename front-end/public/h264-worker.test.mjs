import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const workerSource = fs.readFileSync(
  new URL('./h264-worker.js', import.meta.url),
  'utf8'
);

const avccIdr = new Uint8Array([0, 0, 0, 3, 0x65, 0x88, 0x84]);
const malformedAvcc = new Uint8Array([0, 0, 0, 3, 0xd3, 0x41, 0xe2]);
const avccSpsPpsIdr = new Uint8Array([
  0, 0, 0, 4, 0x67, 0x42, 0xe0, 0x15, 0, 0, 0, 2, 0x68, 0xce, 0, 0, 0, 3, 0x65,
  0x88, 0x84
]);
const annexBIdr = new Uint8Array([
  0, 0, 0, 1, 0x67, 0x42, 0xe0, 0x15, 0, 0, 0, 1, 0x68, 0xce, 0, 0, 0, 1, 0x65,
  0x88, 0x84
]);
const avccLengthThatLooksLikeStartCode = (() => {
  const data = new Uint8Array(370);
  data[0] = 0;
  data[1] = 0;
  data[2] = 1;
  data[3] = 0x6e;
  data[4] = 0x41;
  data.fill(0x88, 5);
  return data;
})();

function createWorkerHarness({ rejectHardwareConfigure = false } = {}) {
  const configured = [];
  const decoders = [];
  const decoded = [];
  const posted = [];
  const clock = { now: 1_000 };

  class FakeVideoDecoder {
    static async isConfigSupported(config) {
      return { supported: true, config };
    }

    constructor(callbacks) {
      this.callbacks = callbacks;
      this.decodeQueueSize = 0;
      this.state = 'unconfigured';
      decoders.push(this);
    }

    configure(config) {
      configured.push(config);
      if (
        rejectHardwareConfigure &&
        config.hardwareAcceleration === 'prefer-hardware'
      ) {
        throw new Error('hardware configure rejected');
      }
      this.state = 'configured';
    }

    close() {
      this.state = 'closed';
    }

    decode(chunk) {
      decoded.push(chunk);
    }
  }

  const self = {
    postMessage(message) {
      posted.push(message);
    }
  };
  const context = vm.createContext({
    ArrayBuffer,
    BigInt,
    Date: { now: () => clock.now },
    EncodedVideoChunk: class EncodedVideoChunk {
      constructor(init) {
        Object.assign(this, init);
      }
    },
    Number,
    Uint8Array,
    VideoDecoder: FakeVideoDecoder,
    console: { error() {}, log() {}, warn() {} },
    performance: { now: () => 1 },
    self
  });
  vm.runInContext(workerSource, context);

  const configure = async () => {
    self.onmessage({
      data: {
        type: 'config',
        avcc: new Uint8Array([1, 0x42, 0xe0, 0x1e]).buffer
      }
    });
    await new Promise((resolve) => setImmediate(resolve));
  };

  return { clock, configure, configured, decoded, decoders, posted, self };
}

test('hardware decoder errors fall back to software acceleration', async () => {
  const harness = createWorkerHarness();
  await harness.configure();

  assert.equal(
    harness.configured.at(-1)?.hardwareAcceleration,
    'prefer-hardware'
  );
  harness.decoders
    .at(-1)
    ?.callbacks.error(new Error('hardware decoder stalled'));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(
    harness.configured.at(-1)?.hardwareAcceleration,
    'prefer-software'
  );
});

test('init can skip hardware after a prior worker saw hardware failure', async () => {
  const harness = createWorkerHarness();
  harness.self.onmessage({ data: { type: 'init', preferHardware: false } });
  await harness.configure();

  assert.equal(
    harness.configured.at(-1)?.hardwareAcceleration,
    'prefer-software'
  );
});

test('reset allows the next config frame to rebuild the hardware decoder', async () => {
  const harness = createWorkerHarness();
  await harness.configure();
  harness.self.onmessage({ data: { type: 'reset', retryHardware: true } });
  await harness.configure();

  assert.deepEqual(
    harness.configured.map((config) => config.hardwareAcceleration),
    ['prefer-hardware', 'prefer-hardware']
  );
});

test('fallback decoder errors surface without retrying forever', async () => {
  const harness = createWorkerHarness();
  await harness.configure();
  harness.clock.now = 1_000;
  harness.decoders.at(-1)?.callbacks.error(new Error('hardware failure'));
  await new Promise((resolve) => setImmediate(resolve));

  const configuredBeforeSoftwareError = harness.configured.length;
  harness.clock.now = 1_600;
  harness.decoders.at(-1)?.callbacks.error(new Error('software failure'));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(harness.configured.length, configuredBeforeSoftwareError);
  assert.ok(
    harness.posted.some(
      (message) =>
        message.type === 'decoder-error' && message.accel === 'prefer-software'
    )
  );
  assert.equal(
    harness.posted.some(
      (message) =>
        message.type === 'decoder-backpressure' &&
        message.reason === 'decoder_error'
    ),
    false
  );
});

test('synchronous hardware configure rejection retries software acceleration', async () => {
  const harness = createWorkerHarness({ rejectHardwareConfigure: true });
  await harness.configure();

  assert.deepEqual(
    harness.configured.map((config) => config.hardwareAcceleration),
    ['prefer-hardware', 'prefer-software']
  );
  assert.ok(
    harness.posted.some((message) => message.type === 'hardware-fallback')
  );
});

test('explicit reset retries hardware after fallback decoder failure', async () => {
  const harness = createWorkerHarness();
  await harness.configure();
  harness.decoders.at(-1)?.callbacks.error(new Error('hardware failure'));
  await new Promise((resolve) => setImmediate(resolve));
  harness.decoders.at(-1)?.callbacks.error(new Error('fallback failure'));

  harness.self.onmessage({ data: { type: 'reset' } });
  await harness.configure();

  assert.equal(
    harness.configured.at(-1)?.hardwareAcceleration,
    'prefer-hardware'
  );
});

test('decoder-error recovery reset preserves hardware fallback state', async () => {
  const harness = createWorkerHarness();
  await harness.configure();
  harness.decoders.at(-1)?.callbacks.error(new Error('hardware failure'));
  await new Promise((resolve) => setImmediate(resolve));

  harness.self.onmessage({ data: { type: 'reset', retryHardware: false } });
  await harness.configure();

  assert.deepEqual(
    harness.configured.map((config) => config.hardwareAcceleration),
    ['prefer-hardware', 'prefer-software', 'prefer-software']
  );
});

test('first IDR after reset is decoded after rebuilding the decoder', async () => {
  const harness = createWorkerHarness();
  await harness.configure();
  harness.self.onmessage({ data: { type: 'reset' } });
  harness.self.onmessage({
    data: {
      type: 'frame',
      isKey: true,
      ptsUs: 1,
      frameData: avccIdr
    }
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(harness.decoded.length, 1);
});

test('IDR payload is decoded as key even when wire key flag is false', async () => {
  const harness = createWorkerHarness();
  await harness.configure();
  harness.self.onmessage({
    data: {
      type: 'frame',
      isKey: false,
      ptsUs: 1,
      frameData: avccSpsPpsIdr
    }
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(harness.decoded.length, 1);
  assert.equal(harness.decoded[0].type, 'key');
});

test('inline SPS/PPS are preserved on IDR chunks', async () => {
  const harness = createWorkerHarness();
  await harness.configure();
  harness.self.onmessage({
    data: {
      type: 'frame',
      isKey: true,
      ptsUs: 1,
      frameData: avccSpsPpsIdr
    }
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(harness.decoded.length, 1);
  assert.deepEqual(
    Array.from(new Uint8Array(harness.decoded[0].data)),
    Array.from(avccSpsPpsIdr)
  );
});

test('raw Annex-B access units are rejected at the AVCC browser boundary', async () => {
  const harness = createWorkerHarness();
  await harness.configure();
  harness.self.onmessage({
    data: {
      type: 'frame',
      isKey: true,
      ptsUs: 1,
      frameData: annexBIdr
    }
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(harness.decoded.length, 0);
  assert.ok(
    harness.posted.some(
      (message) =>
        message.type === 'decoder-backpressure' &&
        message.reason === 'invalid_h264_payload'
    )
  );
});

test('AVCC length prefixes that start with 000001 are not treated as Annex-B', async () => {
  const harness = createWorkerHarness();
  await harness.configure();
  harness.self.onmessage({
    data: {
      type: 'frame',
      isKey: true,
      ptsUs: 1,
      frameData: avccIdr
    }
  });
  harness.self.onmessage({
    data: {
      type: 'frame',
      isKey: false,
      ptsUs: 2,
      frameData: avccLengthThatLooksLikeStartCode
    }
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(harness.decoded.length, 2);
  assert.equal(harness.decoded[1].type, 'delta');
  assert.deepEqual(
    Array.from(new Uint8Array(harness.decoded[1].data)),
    Array.from(avccLengthThatLooksLikeStartCode)
  );
});

test('malformed NAL headers are rejected before WebCodecs decode', async () => {
  const harness = createWorkerHarness();
  await harness.configure();
  harness.self.onmessage({
    data: {
      type: 'frame',
      isKey: true,
      ptsUs: 1,
      frameData: avccIdr
    }
  });
  harness.self.onmessage({
    data: {
      type: 'frame',
      isKey: false,
      ptsUs: 2,
      frameData: malformedAvcc
    }
  });

  assert.equal(harness.decoded.length, 1);
  assert.ok(
    harness.posted.some(
      (message) =>
        message.type === 'decoder-backpressure' &&
        message.reason === 'invalid_h264_payload'
    )
  );
});
