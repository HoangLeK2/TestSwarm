import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const workerSource = fs.readFileSync(
  new URL('./h264-worker.js', import.meta.url),
  'utf8'
);

function createWorkerHarness({ rejectHardwareConfigure = false } = {}) {
  const configured = [];
  const decoders = [];
  const decoded = [];
  const posted = [];

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
    Date,
    EncodedVideoChunk: class EncodedVideoChunk {},
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

  return { configure, configured, decoded, decoders, posted, self };
}

test('hardware decoder errors fall back without forcing software', async () => {
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
    'no-preference'
  );
});

test('reset allows the next config frame to rebuild the hardware decoder', async () => {
  const harness = createWorkerHarness();
  await harness.configure();
  harness.self.onmessage({ data: { type: 'reset' } });
  await harness.configure();

  assert.deepEqual(
    harness.configured.map((config) => config.hardwareAcceleration),
    ['prefer-hardware', 'prefer-hardware']
  );
});

test('fallback decoder errors surface without retrying forever', async () => {
  const harness = createWorkerHarness();
  await harness.configure();
  harness.decoders.at(-1)?.callbacks.error(new Error('hardware failure'));
  await new Promise((resolve) => setImmediate(resolve));

  const configuredBeforeSoftwareError = harness.configured.length;
  harness.decoders.at(-1)?.callbacks.error(new Error('software failure'));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(harness.configured.length, configuredBeforeSoftwareError);
  assert.ok(
    harness.posted.some(
      (message) =>
        message.type === 'decoder-error' && message.accel === 'no-preference'
    )
  );
});

test('synchronous hardware configure rejection retries no-preference', async () => {
  const harness = createWorkerHarness({ rejectHardwareConfigure: true });
  await harness.configure();

  assert.deepEqual(
    harness.configured.map((config) => config.hardwareAcceleration),
    ['prefer-hardware', 'no-preference']
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

test('first IDR after reset is decoded after rebuilding the decoder', async () => {
  const harness = createWorkerHarness();
  await harness.configure();
  harness.self.onmessage({ data: { type: 'reset' } });
  harness.self.onmessage({
    data: {
      type: 'frame',
      isKey: true,
      ptsUs: 1,
      frameData: new Uint8Array([0, 0, 0, 1, 0x65])
    }
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(harness.decoded.length, 1);
});
