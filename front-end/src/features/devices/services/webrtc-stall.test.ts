import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_STALL_THRESHOLDS,
  MAX_CONCURRENT_ATTACHES,
  MAX_RECOVERY_ATTEMPTS,
  acquireKeyframeRepair,
  acquireRecoverySlot,
  classifyStall,
  recoveryDelayMs,
  resetAttachSlotsForTest,
  resetKeyframeRepairsForTest,
  resetRecoverySlotsForTest,
  shouldRequestWebRtcRefreshAfterInput,
  startMediaProgressWatcher,
  waitForAttachSlot,
  type MediaSample
} from './webrtc-stall';

function sample(overrides: Partial<MediaSample> = {}): MediaSample {
  return {
    at: 0,
    bytesReceived: 1000,
    framesDecoded: 10,
    connectionState: 'connected',
    trackEnded: false,
    ...overrides
  };
}

test('a decoded frame clears any suspicion', () => {
  const anchor = sample({ at: 0 });
  const latest = sample({ at: 60_000, framesDecoded: 11, bytesReceived: 1000 });
  assert.equal(classifyStall(anchor, latest), null);
});

test('an idle screen stays healthy with flat counters indefinitely', () => {
  const anchor = sample({ at: 0 });
  const latest = sample({ at: 10 * 60_000 });
  assert.equal(classifyStall(anchor, latest), null);
});

test('bytes arriving with no decoded frame reports decoder_stalled', () => {
  const anchor = sample({ at: 0 });
  const latest = sample({
    at: DEFAULT_STALL_THRESHOLDS.decoderStallMs,
    bytesReceived: 5000
  });
  assert.equal(classifyStall(anchor, latest), 'decoder_stalled');
});

test('a brief decoder pause does not recycle a healthy connection', () => {
  const anchor = sample({ at: 0 });
  const latest = sample({ at: 7_000, bytesReceived: 5000 });
  assert.equal(classifyStall(anchor, latest), null);
});

test('a missing first frame uses the first-frame budget', () => {
  const anchor = sample({ at: 0, framesDecoded: 0, bytesReceived: 0 });
  const inside = sample({
    at: DEFAULT_STALL_THRESHOLDS.firstFrameMs - 1,
    framesDecoded: 0,
    bytesReceived: 0
  });
  assert.equal(classifyStall(anchor, inside), null);
  const outside = sample({
    at: DEFAULT_STALL_THRESHOLDS.firstFrameMs,
    framesDecoded: 0,
    bytesReceived: 0
  });
  assert.equal(classifyStall(anchor, outside), 'no_media');
});

test('RTP arriving without a first decoded frame asks for decoder repair', () => {
  const anchor = sample({ at: 0, framesDecoded: 0, bytesReceived: 0 });
  const latest = sample({
    at: DEFAULT_STALL_THRESHOLDS.firstFrameMs,
    framesDecoded: 0,
    bytesReceived: 10_000
  });
  assert.equal(classifyStall(anchor, latest), 'decoder_stalled');
});

test('a failed connection is reported without waiting for a counter window', () => {
  const anchor = sample({ at: 0 });
  const latest = sample({ at: 10, connectionState: 'failed' });
  assert.equal(classifyStall(anchor, latest), 'connection_failed');
});

test('an ended track is reported the same way', () => {
  const anchor = sample({ at: 0 });
  const latest = sample({ at: 10, trackEnded: true });
  assert.equal(classifyStall(anchor, latest), 'connection_failed');
});

test('the first recovery is immediate and later ones back off with jitter', () => {
  assert.equal(recoveryDelayMs(0), 0);
  assert.equal(
    recoveryDelayMs(1, () => 0.5),
    2_000
  );
  assert.equal(
    recoveryDelayMs(1, () => 0),
    1_600
  );
  assert.equal(
    recoveryDelayMs(1, () => 1),
    2_400
  );
  // Past the table the delay is clamped rather than growing without bound.
  assert.equal(
    recoveryDelayMs(MAX_RECOVERY_ATTEMPTS + 5, () => 0.5),
    30_000
  );
});

test('concurrent recoveries are capped and slots are returned', () => {
  resetRecoverySlotsForTest();
  const first = acquireRecoverySlot();
  const second = acquireRecoverySlot();
  assert.ok(first);
  assert.ok(second);
  assert.equal(acquireRecoverySlot(), null);
  first?.();
  assert.ok(acquireRecoverySlot());
  resetRecoverySlotsForTest();
});

test('a slot release is idempotent', () => {
  resetRecoverySlotsForTest();
  const release = acquireRecoverySlot();
  release?.();
  release?.();
  assert.ok(acquireRecoverySlot());
  assert.ok(acquireRecoverySlot());
  assert.equal(acquireRecoverySlot(), null);
  resetRecoverySlotsForTest();
});

test('keyframe repair is shared and rate-limited per device', () => {
  resetKeyframeRepairsForTest();
  assert.equal(acquireKeyframeRepair('SERIAL-1', 10_000), true);
  assert.equal(acquireKeyframeRepair('SERIAL-1', 12_000), false);
  assert.equal(acquireKeyframeRepair('SERIAL-2', 12_000), true);
  assert.equal(acquireKeyframeRepair('SERIAL-1', 14_000), true);
  resetKeyframeRepairsForTest();
});

test('input refresh is skipped when media progressed after the command', () => {
  assert.equal(shouldRequestWebRtcRefreshAfterInput(12, 12), true);
  assert.equal(shouldRequestWebRtcRefreshAfterInput(12, 13), false);
});

test('a missing first frame is only reported after two samples', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  let clock = 0;
  const reasons: string[] = [];
  const watcher = startMediaProgressWatcher({
    sample: async () =>
      sample({ at: clock, bytesReceived: 0, framesDecoded: 0 }),
    onStall: (reason) => reasons.push(reason),
    isVisible: () => true
  });

  const tick = async (advanceMs: number) => {
    clock += advanceMs;
    t.mock.timers.tick(1_000);
    // The tick body awaits sample(); let the microtask queue drain.
    await Promise.resolve();
    await Promise.resolve();
  };

  await tick(0); // arms the anchor
  await tick(DEFAULT_STALL_THRESHOLDS.firstFrameMs);
  assert.deepEqual(reasons, [], 'one flat sample is scheduling noise');
  await tick(1_000);
  assert.deepEqual(reasons, ['no_media']);
  await tick(1_000);
  assert.deepEqual(reasons, ['no_media'], 'the watcher fires once, then stops');
  watcher.stop();
  t.mock.timers.reset();
});

test('a hidden tab re-arms instead of reporting the hidden period', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  let clock = 0;
  let visible = true;
  const reasons: string[] = [];
  const watcher = startMediaProgressWatcher({
    sample: async () => sample({ at: clock }),
    onStall: (reason) => reasons.push(reason),
    isVisible: () => visible
  });

  const tick = async (advanceMs: number) => {
    clock += advanceMs;
    t.mock.timers.tick(1_000);
    await Promise.resolve();
    await Promise.resolve();
  };

  await tick(0);
  visible = false;
  await tick(60_000);
  visible = true;
  await tick(1_000); // re-arms the anchor at the new clock
  await tick(1_000);
  assert.deepEqual(reasons, []);
  watcher.stop();
  t.mock.timers.reset();
});

test('resume re-arms the watcher after an in-place repair', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  let clock = 0;
  // Bytes keep arriving, nothing decodes: the decoder_stalled signature the
  // recovery path exists for.
  let bytes = 1_000;
  let frames = 10;
  const reasons: string[] = [];
  const progress: number[] = [];
  const watcher = startMediaProgressWatcher({
    sample: async () =>
      sample({ at: clock, bytesReceived: bytes, framesDecoded: frames }),
    onStall: (reason) => reasons.push(reason),
    onProgress: (latest) => progress.push(latest.framesDecoded),
    isVisible: () => true
  });

  const tick = async (advanceMs: number) => {
    clock += advanceMs;
    bytes += 5_000;
    t.mock.timers.tick(1_000);
    await Promise.resolve();
    await Promise.resolve();
  };

  await tick(0); // arms the anchor
  await tick(DEFAULT_STALL_THRESHOLDS.decoderStallMs);
  await tick(1_000);
  assert.deepEqual(reasons, ['decoder_stalled']);

  // Still stalled, but the watcher is paused, so nothing is reported twice.
  await tick(10_000);
  assert.deepEqual(reasons, ['decoder_stalled']);

  // The repair landed: frames move again and the re-armed watcher stays quiet.
  watcher.resume();
  frames += 1;
  await tick(1_000);
  assert.deepEqual(reasons, ['decoder_stalled']);
  assert.deepEqual(progress, [11], 'the repaired IDR clears stalled state');

  // It did not stay fixed. The watcher is live again and reports the next stall,
  // which is what lets the caller escalate past the keyframe rung.
  await tick(DEFAULT_STALL_THRESHOLDS.decoderStallMs);
  await tick(1_000);
  assert.deepEqual(reasons, ['decoder_stalled', 'decoder_stalled']);

  watcher.stop();
  watcher.resume();
  await tick(60_000);
  assert.deepEqual(
    reasons,
    ['decoder_stalled', 'decoder_stalled'],
    'resume after stop stays stopped'
  );
  t.mock.timers.reset();
});

test('attach slots queue FIFO past the cap and hand over on release', async () => {
  resetAttachSlotsForTest();
  const held: Array<() => void> = [];
  for (let i = 0; i < MAX_CONCURRENT_ATTACHES; i += 1) {
    held.push(await waitForAttachSlot());
  }
  const order: string[] = [];
  const first = waitForAttachSlot().then((release) => {
    order.push('first');
    return release;
  });
  const aborted = new AbortController();
  const skipped = waitForAttachSlot(aborted.signal).then(
    () => order.push('skipped'),
    () => order.push('aborted')
  );
  const second = waitForAttachSlot().then((release) => {
    order.push('second');
    return release;
  });
  aborted.abort();
  await skipped;
  assert.deepEqual(order, ['aborted']);

  held[0]();
  held[0](); // double release must not free a second slot
  const releaseFirst = await first;
  assert.deepEqual(order, ['aborted', 'first']);

  releaseFirst();
  await second;
  assert.deepEqual(order, ['aborted', 'first', 'second']);
  resetAttachSlotsForTest();
});

test('interactive attach jumps ahead of queued previews', async () => {
  resetAttachSlotsForTest();
  const held: Array<() => void> = [];
  for (let i = 0; i < MAX_CONCURRENT_ATTACHES; i += 1) {
    held.push(await waitForAttachSlot(undefined, 'preview'));
  }
  const order: string[] = [];
  const preview = waitForAttachSlot(undefined, 'preview').then((release) => {
    order.push('preview');
    return release;
  });
  const interactive = waitForAttachSlot(undefined, 'interactive').then(
    (release) => {
      order.push('interactive');
      return release;
    }
  );

  held.shift()?.();
  const releaseInteractive = await interactive;
  assert.deepEqual(order, ['interactive']);
  releaseInteractive();
  const releasePreview = await preview;
  assert.deepEqual(order, ['interactive', 'preview']);

  releasePreview();
  held.forEach((release) => release());
  resetAttachSlotsForTest();
});
