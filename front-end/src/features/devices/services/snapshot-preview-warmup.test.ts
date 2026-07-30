import assert from 'node:assert/strict';
import test from 'node:test';

process.env.NEXT_PUBLIC_DEVICE_FARM_PREVIEW_ATTACH_CONCURRENCY = '2';
process.env.NEXT_PUBLIC_DEVICE_FARM_SNAPSHOT_WARMUP_RELEASE_GRACE_MS = '20';
process.env.NEXT_PUBLIC_DEVICE_FARM_SNAPSHOT_WARMUP_RETAINED_IDLE_LIMIT = '2';

const farmApiModule = await import('@/lib/farm-api');

type FarmApiPost = (
  url: string,
  payload?: unknown,
  config?: unknown
) => Promise<{ data: unknown }>;

const postCalls: Array<{ url: string; payload: unknown; config: unknown }> = [];
const blockedAttachSerials = new Set<string>();
const failedAttachSerials = new Set<string>();
const blockedAttachResolvers = new Map<string, () => void>();

(farmApiModule.farmApi as unknown as { post: FarmApiPost }).post = async (
  url,
  payload,
  config
) => {
  postCalls.push({ url, payload, config });
  const attachMatch = url.match(/\/devices\/([^/]+)\/scrcpy\/attach/);
  const attachSerial = attachMatch?.[1];
  if (attachSerial && failedAttachSerials.has(attachSerial)) {
    throw new Error(`attach failed for ${attachSerial}`);
  }
  if (attachSerial && blockedAttachSerials.has(attachSerial)) {
    await new Promise<void>((resolve, reject) => {
      blockedAttachResolvers.set(attachSerial, resolve);
      const signal = (config as { signal?: AbortSignal } | undefined)?.signal;
      if (signal?.aborted) {
        reject({ name: 'CanceledError' });
        return;
      }
      signal?.addEventListener(
        'abort',
        () => reject({ name: 'CanceledError' }),
        { once: true }
      );
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

test('snapshot preview queues visible phones and starts them in FIFO order', async (t) => {
  blockedAttachSerials.add('serial-a');
  blockedAttachSerials.add('serial-b');
  t.after(() => {
    for (const serial of ['serial-a', 'serial-b']) {
      blockedAttachSerials.delete(serial);
      blockedAttachResolvers.get(serial)?.();
      blockedAttachResolvers.delete(serial);
    }
  });

  const first = warmup.acquireSnapshotPreviewWarmup('serial-a');
  const second = warmup.acquireSnapshotPreviewWarmup('serial-b');
  const third = warmup.acquireSnapshotPreviewWarmup('serial-c');

  assert.ok(first);
  assert.ok(second);
  assert.ok(third);
  assert.equal(await first.started, true);
  assert.equal(await second.started, true);
  let thirdStarted = false;
  void third.started.then((started) => {
    thirdStarted = started;
  });
  await flushMicrotasks();
  assert.equal(thirdStarted, false);
  assert.equal(warmup.getSnapshotPreviewAttachConcurrency(), 2);
  assert.equal(warmup.getSnapshotPreviewWarmupActiveCount(), 3);
  assert.equal(warmup.getSnapshotPreviewAttachingCount(), 2);
  assert.equal(
    postCalls.some((call) =>
      call.url.includes('/devices/serial-c/scrcpy/attach')
    ),
    false
  );

  blockedAttachSerials.delete('serial-a');
  blockedAttachResolvers.get('serial-a')?.();
  blockedAttachResolvers.delete('serial-a');
  await first.attached;
  await flushMicrotasks();
  assert.equal(await third.started, true);
  assert.equal(warmup.getSnapshotPreviewAttachingCount(), 2);
  assert.ok(
    postCalls.some((call) =>
      call.url.includes('/devices/serial-c/scrcpy/attach')
    )
  );
  await third.attached;

  blockedAttachSerials.delete('serial-b');
  blockedAttachResolvers.get('serial-b')?.();
  blockedAttachResolvers.delete('serial-b');
  await second.attached;

  first.release();
  second.release();
  third.release();
  await waitForReleaseGrace();
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
  const config = attachCall.config as {
    timeout?: number;
    _skip429Retry?: boolean;
    signal?: AbortSignal;
  };
  assert.equal(config.timeout, 10_000);
  assert.equal(config._skip429Retry, true);
  assert.ok(config.signal instanceof AbortSignal);
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

test('snapshot preview release grace does not block a new visible serial', async () => {
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
  assert.equal(warmup.getSnapshotPreviewWarmupActiveCount(), 3);
  assert.equal(
    postCalls.some((call) =>
      call.url.includes('/devices/serial-evict-a/scrcpy/detach')
    ),
    false
  );

  await waitForReleaseGrace();
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

test('snapshot preview caps retained offscreen live previews', async () => {
  postCalls.length = 0;

  const first = warmup.acquireSnapshotPreviewWarmup('serial-retain-limit-a');
  const second = warmup.acquireSnapshotPreviewWarmup('serial-retain-limit-b');
  const third = warmup.acquireSnapshotPreviewWarmup('serial-retain-limit-c');
  assert.ok(first);
  assert.ok(second);
  assert.ok(third);
  await Promise.all([first.attached, second.attached, third.attached]);

  first.release();
  second.release();
  third.release();
  await flushMicrotasks();

  assert.equal(warmup.getSnapshotPreviewRetainedIdleLimit(), 2);
  assert.equal(warmup.getSnapshotPreviewWarmupActiveCount(), 2);
  assert.ok(
    postCalls.some((call) =>
      call.url.includes('/devices/serial-retain-limit-a/scrcpy/detach')
    )
  );
  assert.equal(
    postCalls.some((call) =>
      call.url.includes('/devices/serial-retain-limit-b/scrcpy/detach')
    ),
    false
  );
  assert.equal(
    postCalls.some((call) =>
      call.url.includes('/devices/serial-retain-limit-c/scrcpy/detach')
    ),
    false
  );

  await waitForReleaseGrace();
});

test('snapshot preview drops a queued phone that leaves the viewport', async (t) => {
  const firstPendingSerial = 'serial-queued-a';
  const secondPendingSerial = 'serial-queued-b';
  const queuedSerial = 'serial-queued-c';
  blockedAttachSerials.add(firstPendingSerial);
  blockedAttachSerials.add(secondPendingSerial);
  t.after(() => {
    for (const serial of [firstPendingSerial, secondPendingSerial]) {
      blockedAttachSerials.delete(serial);
      blockedAttachResolvers.get(serial)?.();
      blockedAttachResolvers.delete(serial);
    }
  });

  const pending = warmup.acquireSnapshotPreviewWarmup(firstPendingSerial);
  const second = warmup.acquireSnapshotPreviewWarmup(secondPendingSerial);
  const queued = warmup.acquireSnapshotPreviewWarmup(queuedSerial);
  assert.ok(pending);
  assert.ok(second);
  assert.ok(queued);
  assert.equal(warmup.getSnapshotPreviewAttachingCount(), 2);

  queued.release();
  assert.equal(await queued.attached, false);
  assert.equal(
    postCalls.some((call) =>
      call.url.includes(`/devices/${queuedSerial}/scrcpy/attach`)
    ),
    false
  );

  blockedAttachSerials.delete(firstPendingSerial);
  blockedAttachResolvers.get(firstPendingSerial)?.();
  blockedAttachResolvers.delete(firstPendingSerial);
  await pending.attached;

  blockedAttachSerials.delete(secondPendingSerial);
  blockedAttachResolvers.get(secondPendingSerial)?.();
  blockedAttachResolvers.delete(secondPendingSerial);
  await second.attached;

  pending.release();
  second.release();
  await waitForReleaseGrace();
});

test('snapshot preview aborts an attaching phone that leaves and advances the FIFO queue', async (t) => {
  const firstPendingSerial = 'serial-cancel-a';
  const secondPendingSerial = 'serial-cancel-b';
  const queuedSerial = 'serial-cancel-c';
  blockedAttachSerials.add(firstPendingSerial);
  blockedAttachSerials.add(secondPendingSerial);
  t.after(() => {
    for (const serial of [firstPendingSerial, secondPendingSerial]) {
      blockedAttachSerials.delete(serial);
      blockedAttachResolvers.get(serial)?.();
      blockedAttachResolvers.delete(serial);
    }
  });

  const first = warmup.acquireSnapshotPreviewWarmup(firstPendingSerial);
  const second = warmup.acquireSnapshotPreviewWarmup(secondPendingSerial);
  const queued = warmup.acquireSnapshotPreviewWarmup(queuedSerial);
  assert.ok(first);
  assert.ok(second);
  assert.ok(queued);
  t.after(() => {
    first.release();
    second.release();
    queued.release();
  });

  await flushMicrotasks();
  const firstAttachCall = postCalls.find((call) =>
    call.url.includes(`/devices/${firstPendingSerial}/scrcpy/attach`)
  );
  const firstSignal = (
    firstAttachCall?.config as { signal?: AbortSignal } | undefined
  )?.signal;
  assert.ok(firstSignal);
  assert.equal(firstSignal.aborted, false);

  first.release();
  assert.equal(firstSignal.aborted, true);
  assert.equal(await first.attached, false);
  assert.equal(await queued.attached, true);
  assert.ok(
    postCalls.some((call) =>
      call.url.includes(`/devices/${queuedSerial}/scrcpy/attach`)
    )
  );

  blockedAttachSerials.delete(secondPendingSerial);
  blockedAttachResolvers.get(secondPendingSerial)?.();
  blockedAttachResolvers.delete(secondPendingSerial);
  await second.attached;

  second.release();
  queued.release();
  await waitForReleaseGrace();
});

test('snapshot preview advances the FIFO queue after an attach failure', async (t) => {
  const failedSerial = 'serial-failure-a';
  const blockedSerial = 'serial-failure-b';
  const queuedSerial = 'serial-failure-c';
  failedAttachSerials.add(failedSerial);
  blockedAttachSerials.add(blockedSerial);
  t.after(() => {
    failedAttachSerials.delete(failedSerial);
    blockedAttachSerials.delete(blockedSerial);
    blockedAttachResolvers.get(blockedSerial)?.();
    blockedAttachResolvers.delete(blockedSerial);
  });

  const failed = warmup.acquireSnapshotPreviewWarmup(failedSerial);
  const blocked = warmup.acquireSnapshotPreviewWarmup(blockedSerial);
  const queued = warmup.acquireSnapshotPreviewWarmup(queuedSerial);
  assert.ok(failed);
  assert.ok(blocked);
  assert.ok(queued);
  t.after(() => {
    failed.release();
    blocked.release();
    queued.release();
  });

  assert.equal(await failed.attached, false);
  assert.equal(await queued.attached, true);
  assert.ok(
    postCalls.some((call) =>
      call.url.includes(`/devices/${queuedSerial}/scrcpy/attach`)
    )
  );

  blockedAttachSerials.delete(blockedSerial);
  blockedAttachResolvers.get(blockedSerial)?.();
  blockedAttachResolvers.delete(blockedSerial);
  await blocked.attached;
  blocked.release();
  queued.release();
  await waitForReleaseGrace();
});

test('snapshot preview does not let a canceled serial reuse its old FIFO position', async (t) => {
  const firstSerial = 'serial-fairness-a';
  const secondSerial = 'serial-fairness-b';
  const canceledSerial = 'serial-fairness-c';
  const nextSerial = 'serial-fairness-d';
  for (const serial of [firstSerial, secondSerial, nextSerial]) {
    blockedAttachSerials.add(serial);
  }
  t.after(() => {
    for (const serial of [
      firstSerial,
      secondSerial,
      canceledSerial,
      nextSerial
    ]) {
      blockedAttachSerials.delete(serial);
      blockedAttachResolvers.get(serial)?.();
      blockedAttachResolvers.delete(serial);
    }
  });

  const first = warmup.acquireSnapshotPreviewWarmup(firstSerial);
  const second = warmup.acquireSnapshotPreviewWarmup(secondSerial);
  const canceled = warmup.acquireSnapshotPreviewWarmup(canceledSerial);
  const next = warmup.acquireSnapshotPreviewWarmup(nextSerial);
  assert.ok(first);
  assert.ok(second);
  assert.ok(canceled);
  assert.ok(next);
  canceled.release();
  assert.equal(await canceled.started, false);

  const reacquired = warmup.acquireSnapshotPreviewWarmup(canceledSerial);
  assert.ok(reacquired);
  t.after(() => {
    first.release();
    second.release();
    next.release();
    reacquired.release();
  });

  blockedAttachSerials.delete(firstSerial);
  blockedAttachResolvers.get(firstSerial)?.();
  blockedAttachResolvers.delete(firstSerial);
  await first.attached;
  await flushMicrotasks();

  assert.equal(await next.started, true);
  assert.equal(
    postCalls.some((call) =>
      call.url.includes(`/devices/${canceledSerial}/scrcpy/attach`)
    ),
    false
  );

  blockedAttachSerials.delete(nextSerial);
  blockedAttachResolvers.get(nextSerial)?.();
  blockedAttachResolvers.delete(nextSerial);
  await next.attached;
  assert.equal(await reacquired.started, true);
  assert.equal(await reacquired.attached, true);

  blockedAttachSerials.delete(secondSerial);
  blockedAttachResolvers.get(secondSerial)?.();
  blockedAttachResolvers.delete(secondSerial);
  await second.attached;
  first.release();
  second.release();
  next.release();
  reacquired.release();
  await waitForReleaseGrace();
});

test('snapshot preview creates a fresh entry when an attaching phone re-enters', async (t) => {
  const canceledSerial = 'serial-reenter-a';
  const blockerSerial = 'serial-reenter-b';
  const queuedSerial = 'serial-reenter-c';
  blockedAttachSerials.add(canceledSerial);
  blockedAttachSerials.add(blockerSerial);
  blockedAttachSerials.add(queuedSerial);
  t.after(() => {
    for (const serial of [canceledSerial, blockerSerial, queuedSerial]) {
      blockedAttachSerials.delete(serial);
      blockedAttachResolvers.get(serial)?.();
      blockedAttachResolvers.delete(serial);
    }
  });

  const canceled = warmup.acquireSnapshotPreviewWarmup(canceledSerial);
  const blocker = warmup.acquireSnapshotPreviewWarmup(blockerSerial);
  const queued = warmup.acquireSnapshotPreviewWarmup(queuedSerial);
  assert.ok(canceled);
  assert.ok(blocker);
  assert.ok(queued);
  await flushMicrotasks();

  canceled.release();
  const reacquired = warmup.acquireSnapshotPreviewWarmup(canceledSerial);
  assert.ok(reacquired);
  assert.notEqual(reacquired.attached, canceled.attached);
  t.after(() => {
    blocker.release();
    queued.release();
    reacquired.release();
  });

  assert.equal(await canceled.attached, false);
  assert.equal(await queued.started, true);
  let reacquiredStarted = false;
  void reacquired.started.then((started) => {
    reacquiredStarted = started;
  });
  await flushMicrotasks();
  assert.equal(reacquiredStarted, false);

  blockedAttachSerials.delete(queuedSerial);
  blockedAttachResolvers.get(queuedSerial)?.();
  blockedAttachResolvers.delete(queuedSerial);
  await queued.attached;
  assert.equal(await reacquired.started, true);

  blockedAttachSerials.delete(canceledSerial);
  blockedAttachResolvers.get(canceledSerial)?.();
  blockedAttachResolvers.delete(canceledSerial);
  await reacquired.attached;
  blockedAttachSerials.delete(blockerSerial);
  blockedAttachResolvers.get(blockerSerial)?.();
  blockedAttachResolvers.delete(blockerSerial);
  await blocker.attached;
  blocker.release();
  queued.release();
  reacquired.release();
  await waitForReleaseGrace();
});
