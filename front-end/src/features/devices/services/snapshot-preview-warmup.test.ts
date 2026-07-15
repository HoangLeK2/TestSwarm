import assert from 'node:assert/strict';
import test from 'node:test';

process.env.NEXT_PUBLIC_DEVICE_FARM_SNAPSHOT_WARMUP_LIMIT = '2';
process.env.NEXT_PUBLIC_DEVICE_FARM_SNAPSHOT_WARMUP_RELEASE_GRACE_MS = '20';

const farmApiModule = await import('@/lib/farm-api');

type FarmApiPost = (
  url: string,
  payload?: unknown,
  config?: unknown
) => Promise<{ data: unknown }>;

const postCalls: Array<{ url: string; payload: unknown; config: unknown }> = [];
const blockedAttachSerials = new Set<string>();
const blockedAttachResolvers = new Map<string, () => void>();

(farmApiModule.farmApi as unknown as { post: FarmApiPost }).post = async (
  url,
  payload,
  config
) => {
  postCalls.push({ url, payload, config });
  const attachMatch = url.match(/\/devices\/([^/]+)\/scrcpy\/attach/);
  const attachSerial = attachMatch?.[1];
  if (attachSerial && blockedAttachSerials.has(attachSerial)) {
    await new Promise<void>((resolve) => {
      blockedAttachResolvers.set(attachSerial, resolve);
    });
  }
  return { data: { ok: true } };
};

const warmup = await import('./snapshot-preview-warmup');

function flushMicrotasks(): Promise<void> {
  return new Promise((resolve) => queueMicrotask(resolve));
}

function waitForReleaseGrace(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 30));
}

test('snapshot preview warmup caps concurrent preview attaches and notifies on release', async () => {
  const events: number[] = [];
  const unsubscribe = warmup.subscribeSnapshotPreviewWarmupChanges(() => {
    events.push(warmup.getSnapshotPreviewWarmupActiveCount());
  });

  const first = warmup.acquireSnapshotPreviewWarmup('serial-a');
  const second = warmup.acquireSnapshotPreviewWarmup('serial-b');
  const overLimit = warmup.acquireSnapshotPreviewWarmup('serial-c');

  assert.ok(first);
  assert.ok(second);
  assert.equal(overLimit, null);
  assert.equal(warmup.getSnapshotPreviewWarmupLimit(), 2);
  assert.equal(warmup.getSnapshotPreviewWarmupActiveCount(), 2);

  await Promise.all([first.attached, second.attached]);
  first.release();
  assert.equal(warmup.getSnapshotPreviewWarmupActiveCount(), 2);
  await waitForReleaseGrace();
  await flushMicrotasks();

  assert.equal(warmup.getSnapshotPreviewWarmupActiveCount(), 1);
  assert.ok(events.includes(1));

  const third = warmup.acquireSnapshotPreviewWarmup('serial-c');
  assert.ok(third);
  await third.attached;

  second.release();
  third.release();
  await waitForReleaseGrace();
  unsubscribe();
});

test('snapshot preview warmup uses lightweight scrcpy attach profile', async () => {
  postCalls.length = 0;

  const handle = warmup.acquireSnapshotPreviewWarmup('serial-profile');
  assert.ok(handle);
  await handle.attached;
  handle.release();
  await waitForReleaseGrace();

  const attachCall = postCalls.find((call) =>
    call.url.includes('/devices/serial-profile/scrcpy/attach')
  );
  assert.ok(attachCall);
  const payload = attachCall.payload as {
    viewer_id?: string;
    enable_control?: boolean;
    max_fps?: number;
    max_width?: number;
    bitrate?: number;
  };
  assert.match(payload.viewer_id ?? '', /^snapshot-preview:/);
  assert.deepEqual(payload, {
    viewer_id: payload.viewer_id,
    enable_control: true,
    max_fps: 1,
    max_width: 360,
    bitrate: 100_000
  });
  assert.deepEqual(attachCall.config, {
    timeout: 10_000,
    _skip429Retry: true
  });
});

test('snapshot preview warmup reuses a viewer reacquired during release grace', async () => {
  postCalls.length = 0;

  const first = warmup.acquireSnapshotPreviewWarmup('serial-retained');
  assert.ok(first);
  await first.attached;
  first.release();

  const reacquired = warmup.acquireSnapshotPreviewWarmup('serial-retained');
  assert.ok(reacquired);
  await reacquired.attached;

  const attachCalls = postCalls.filter((call) =>
    call.url.includes('/devices/serial-retained/scrcpy/attach')
  );
  assert.equal(attachCalls.length, 1);

  reacquired.release();
  await waitForReleaseGrace();
});

test('snapshot preview warmup evicts an unused retained viewer for a new serial', async () => {
  postCalls.length = 0;

  const first = warmup.acquireSnapshotPreviewWarmup('serial-evict-a');
  const second = warmup.acquireSnapshotPreviewWarmup('serial-evict-b');
  assert.ok(first);
  assert.ok(second);
  await Promise.all([first.attached, second.attached]);

  first.release();
  const replacement = warmup.acquireSnapshotPreviewWarmup('serial-evict-c');

  assert.ok(replacement);
  await replacement.attached;
  assert.equal(warmup.getSnapshotPreviewWarmupActiveCount(), 2);
  assert.ok(
    postCalls.some((call) =>
      call.url.includes('/devices/serial-evict-a/scrcpy/detach')
    )
  );

  second.release();
  replacement.release();
  await waitForReleaseGrace();
});

test('snapshot preview warmup keeps pending attaches inside the concurrency cap', async () => {
  const pendingSerial = 'serial-pending-a';
  blockedAttachSerials.add(pendingSerial);

  const pending = warmup.acquireSnapshotPreviewWarmup(pendingSerial);
  const second = warmup.acquireSnapshotPreviewWarmup('serial-pending-b');
  assert.ok(pending);
  assert.ok(second);
  await second.attached;

  pending.release();
  await waitForReleaseGrace();
  assert.equal(warmup.acquireSnapshotPreviewWarmup('serial-pending-c'), null);

  blockedAttachSerials.delete(pendingSerial);
  blockedAttachResolvers.get(pendingSerial)?.();
  blockedAttachResolvers.delete(pendingSerial);
  await pending.attached;
  await flushMicrotasks();

  const replacement = warmup.acquireSnapshotPreviewWarmup('serial-pending-c');
  assert.ok(replacement);
  await replacement.attached;

  second.release();
  replacement.release();
  await waitForReleaseGrace();
});
