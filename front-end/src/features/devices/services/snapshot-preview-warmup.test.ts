import assert from 'node:assert/strict';
import test from 'node:test';

process.env.NEXT_PUBLIC_DEVICE_FARM_SNAPSHOT_WARMUP_LIMIT = '2';

const farmApiModule = await import('@/lib/farm-api');

type FarmApiPost = (
  url: string,
  payload?: unknown,
  config?: unknown
) => Promise<{ data: unknown }>;

const postCalls: Array<{ url: string; payload: unknown; config: unknown }> = [];

(farmApiModule.farmApi as unknown as { post: FarmApiPost }).post = async (
  url,
  payload,
  config
) => {
  postCalls.push({ url, payload, config });
  return { data: { ok: true } };
};

const warmup = await import('./snapshot-preview-warmup');

function flushMicrotasks(): Promise<void> {
  return new Promise((resolve) => queueMicrotask(resolve));
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
  await flushMicrotasks();

  assert.equal(warmup.getSnapshotPreviewWarmupActiveCount(), 1);
  assert.ok(events.includes(1));

  const third = warmup.acquireSnapshotPreviewWarmup('serial-c');
  assert.ok(third);
  await third.attached;

  second.release();
  third.release();
  unsubscribe();
});

test('snapshot preview warmup uses lightweight scrcpy attach profile', async () => {
  postCalls.length = 0;

  const handle = warmup.acquireSnapshotPreviewWarmup('serial-profile');
  assert.ok(handle);
  await handle.attached;
  handle.release();

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
