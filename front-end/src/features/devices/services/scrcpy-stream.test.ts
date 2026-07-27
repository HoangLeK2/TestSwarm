import assert from 'node:assert/strict';
import test from 'node:test';

process.env.NEXT_PUBLIC_DEVICE_FARM_SCRCPY_VIEWER_HEARTBEAT_MS = '1000';

type FarmApiPost = (
  url: string,
  payload?: unknown,
  config?: unknown
) => Promise<{ data: unknown }>;

const postCalls: Array<{ url: string; payload: unknown; config: unknown }> = [];
const blockedHeartbeatSerials = new Set<string>();
const blockedHeartbeatResolvers = new Map<string, () => void>();
const blockedAttachSerials = new Set<string>();
const blockedAttachResolvers = new Map<string, () => void>();
const heartbeatFailuresRemaining = new Map<string, number>();
type ScrcpyStreamModule = typeof import('./scrcpy-stream');
let streamModule: ScrcpyStreamModule | null = null;

async function loadScrcpyStream(): Promise<ScrcpyStreamModule> {
  if (streamModule) return streamModule;
  const farmApiModule = await import('@/lib/farm-api');
  (farmApiModule.farmApi as unknown as { post: FarmApiPost }).post = async (
    url,
    payload,
    config
  ) => {
    postCalls.push({ url, payload, config });
    const attachMatch = url.match(/\/devices\/([^/]+)\/scrcpy\/attach/);
    const attachSerial = attachMatch?.[1];
    if (attachSerial && blockedAttachSerials.has(attachSerial)) {
      const signal = (config as { signal?: AbortSignal } | undefined)?.signal;
      await new Promise<void>((resolve, reject) => {
        const onAbort = () => {
          blockedAttachResolvers.delete(attachSerial);
          reject(
            Object.assign(new Error('attach aborted'), {
              name: 'CanceledError'
            })
          );
        };
        if (signal?.aborted) {
          onAbort();
          return;
        }
        signal?.addEventListener('abort', onAbort, { once: true });
        blockedAttachResolvers.set(attachSerial, () => {
          signal?.removeEventListener('abort', onAbort);
          resolve();
        });
      });
    }
    const heartbeatMatch = url.match(/\/devices\/([^/]+)\/scrcpy\/heartbeat/);
    const heartbeatSerial = heartbeatMatch?.[1];
    if (heartbeatSerial) {
      const failuresRemaining =
        heartbeatFailuresRemaining.get(heartbeatSerial) ?? 0;
      if (failuresRemaining > 0) {
        heartbeatFailuresRemaining.set(heartbeatSerial, failuresRemaining - 1);
        throw Object.assign(new Error('viewer not found'), {
          response: { status: 404 }
        });
      }
    }
    if (heartbeatSerial && blockedHeartbeatSerials.has(heartbeatSerial)) {
      await new Promise<void>((resolve) => {
        blockedHeartbeatResolvers.set(heartbeatSerial, resolve);
      });
    }
    return { data: { ok: true } };
  };
  streamModule = await import('./scrcpy-stream');
  return streamModule;
}

async function waitFor(
  predicate: () => boolean,
  timeoutMs = 2000
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() >= deadline) {
      throw new Error('Timed out waiting for condition');
    }
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
}

test('control screen attach invalidates cached H264 bootstrap frames', async () => {
  const stream = await loadScrcpyStream();
  assert.equal(
    stream.shouldClearH264CacheBeforeScrcpyAttach('device-screen:viewer-1'),
    true
  );
  assert.equal(
    stream.shouldClearH264CacheBeforeScrcpyAttach('control-screen:viewer-2'),
    true
  );
});

test('snapshot preview attach keeps cached H264 bootstrap frames', async () => {
  const stream = await loadScrcpyStream();
  assert.equal(
    stream.shouldClearH264CacheBeforeScrcpyAttach('snapshot-preview:viewer-1'),
    false
  );
});

test('attach cancellation is not treated as a stream failure', async () => {
  const stream = await loadScrcpyStream();

  assert.equal(
    stream.isScrcpyAttachCancellation({ code: 'ERR_CANCELED' }),
    true
  );
  assert.equal(
    stream.isScrcpyAttachCancellation({ name: 'CanceledError' }),
    true
  );
  assert.equal(stream.isScrcpyAttachCancellation(new Error('network')), false);
});

test('control screen attach uses normal retry policy and payload', async () => {
  const stream = await loadScrcpyStream();
  postCalls.length = 0;

  await stream.attachScrcpyStream('serial one', 'device-screen:viewer-1');

  assert.equal(postCalls.length, 1);
  assert.equal(postCalls[0]?.url, '/devices/serial%20one/scrcpy/attach');
  assert.deepEqual(postCalls[0]?.payload, {
    viewer_id: 'device-screen:viewer-1'
  });
  const controlConfig = postCalls[0]?.config as {
    timeout?: number;
    _skip429Retry?: boolean;
    signal?: AbortSignal;
  };
  assert.equal(controlConfig.timeout, 10_000);
  assert.equal(controlConfig._skip429Retry, false);
  assert.equal(controlConfig.signal?.aborted, false);
  await stream.detachScrcpyStream('serial one', 'device-screen:viewer-1');
});

test('snapshot preview attach keeps lightweight no-retry policy', async () => {
  const stream = await loadScrcpyStream();
  postCalls.length = 0;

  await stream.attachScrcpyStream(
    'serial-preview',
    'snapshot-preview:viewer-1',
    {
      enableControl: true,
      maxFps: 1,
      maxWidth: 360,
      bitrate: 100_000
    }
  );

  assert.equal(postCalls.length, 1);
  assert.deepEqual(postCalls[0]?.payload, {
    viewer_id: 'snapshot-preview:viewer-1',
    enable_control: true,
    max_fps: 1,
    max_width: 360,
    bitrate: 100_000
  });
  const previewConfig = postCalls[0]?.config as {
    timeout?: number;
    _skip429Retry?: boolean;
    signal?: AbortSignal;
  };
  assert.equal(previewConfig.timeout, 10_000);
  assert.equal(previewConfig._skip429Retry, true);
  assert.equal(previewConfig.signal?.aborted, false);
  await stream.detachScrcpyStream(
    'serial-preview',
    'snapshot-preview:viewer-1'
  );
});

test('leased viewer heartbeat is lightweight and cannot delay detach', async () => {
  const stream = await loadScrcpyStream();
  postCalls.length = 0;
  const serial = 'serial-heartbeat';
  const viewerId = 'control-screen:heartbeat';

  await stream.attachScrcpyStream(serial, viewerId);
  blockedHeartbeatSerials.add(serial);
  await waitFor(
    () =>
      postCalls.filter((call) => call.url.endsWith('/scrcpy/heartbeat'))
        .length >= 1
  );

  const heartbeatCall = postCalls.find((call) =>
    call.url.endsWith('/scrcpy/heartbeat')
  );
  assert.deepEqual(heartbeatCall?.payload, { viewer_id: viewerId });
  assert.deepEqual(heartbeatCall?.config, { timeout: 10_000 });

  await stream.detachScrcpyStream(serial, viewerId);
  assert.ok(postCalls.some((call) => call.url.endsWith('/scrcpy/detach')));

  const heartbeatCountAfterDetach = postCalls.filter((call) =>
    call.url.endsWith('/scrcpy/heartbeat')
  ).length;
  blockedHeartbeatSerials.delete(serial);
  blockedHeartbeatResolvers.get(serial)?.();
  blockedHeartbeatResolvers.delete(serial);
  await new Promise((resolve) => setTimeout(resolve, 1050));

  assert.equal(
    postCalls.filter((call) => call.url.endsWith('/scrcpy/heartbeat')).length,
    heartbeatCountAfterDetach
  );
});

test('pagehide detach uses fetch keepalive and stops the viewer heartbeat', async () => {
  const stream = await loadScrcpyStream();
  postCalls.length = 0;
  const serial = 'serial-pagehide';
  const viewerId = 'control-screen:pagehide';

  await stream.attachScrcpyStream(serial, viewerId);
  postCalls.length = 0;

  await stream.detachScrcpyStreamOnPageHide(serial, viewerId);

  assert.deepEqual(postCalls[0], {
    url: '/devices/serial-pagehide/scrcpy/detach',
    payload: { viewer_id: viewerId },
    config: {
      timeout: 10_000,
      adapter: 'fetch',
      fetchOptions: { keepalive: true }
    }
  });

  await new Promise((resolve) => setTimeout(resolve, 1050));
  assert.equal(
    postCalls.filter((call) => call.url.endsWith('/scrcpy/heartbeat')).length,
    0
  );
});

test('pagehide aborts a pending attach before sending its detach', async () => {
  const stream = await loadScrcpyStream();
  postCalls.length = 0;
  const serial = 'serial-pagehide-pending';
  const viewerId = 'control-screen:pagehide-pending';
  blockedAttachSerials.add(serial);

  const attachPromise = stream.attachScrcpyStream(serial, viewerId);
  await waitFor(() =>
    postCalls.some((call) => call.url.endsWith('/scrcpy/attach'))
  );
  const attachCall = postCalls.find((call) =>
    call.url.endsWith('/scrcpy/attach')
  );
  const attachSignal = (attachCall?.config as { signal?: AbortSignal } | null)
    ?.signal;

  try {
    await stream.detachScrcpyStreamOnPageHide(serial, viewerId);

    assert.ok(attachSignal);
    assert.equal(attachSignal.aborted, true);
    assert.ok(postCalls.some((call) => call.url.endsWith('/scrcpy/detach')));
  } finally {
    blockedAttachSerials.delete(serial);
    blockedAttachResolvers.get(serial)?.();
    blockedAttachResolvers.delete(serial);
    await attachPromise.catch(() => undefined);
    await stream.detachScrcpyStream(serial, viewerId);
  }
});

test('heartbeat 404 reattaches viewer with its original profile', async () => {
  const stream = await loadScrcpyStream();
  postCalls.length = 0;
  const serial = 'serial-heartbeat-recovery';
  const viewerId = 'snapshot-preview:recovery';
  const options = {
    enableControl: true,
    maxFps: 1,
    maxWidth: 360,
    bitrate: 100_000
  };
  heartbeatFailuresRemaining.set(serial, 1);

  await stream.attachScrcpyStream(serial, viewerId, options);
  blockedAttachSerials.add(serial);
  await waitFor(
    () =>
      postCalls.filter((call) => call.url.endsWith('/scrcpy/attach')).length >=
      2
  );

  const attachCalls = postCalls.filter((call) =>
    call.url.endsWith('/scrcpy/attach')
  );
  assert.deepEqual(attachCalls[1]?.payload, {
    viewer_id: viewerId,
    enable_control: true,
    max_fps: 1,
    max_width: 360,
    bitrate: 100_000
  });

  await stream.detachScrcpyStream(serial, viewerId);
  assert.equal(
    postCalls.filter((call) => call.url.endsWith('/scrcpy/detach')).length,
    1
  );
  blockedAttachSerials.delete(serial);
  blockedAttachResolvers.get(serial)?.();
  blockedAttachResolvers.delete(serial);
  await waitFor(
    () =>
      postCalls.filter((call) => call.url.endsWith('/scrcpy/detach')).length >=
      2
  );

  heartbeatFailuresRemaining.delete(serial);
});

test('explicit attach waits for stale recovery before applying new profile', async () => {
  const stream = await loadScrcpyStream();
  postCalls.length = 0;
  const serial = 'serial-heartbeat-replacement';
  const viewerId = 'control-screen:replacement';
  heartbeatFailuresRemaining.set(serial, 1);

  await stream.attachScrcpyStream(serial, viewerId, { maxFps: 10 });
  blockedAttachSerials.add(serial);
  await waitFor(
    () =>
      postCalls.filter((call) => call.url.endsWith('/scrcpy/attach')).length >=
      2
  );

  const replacement = stream.attachScrcpyStream(serial, viewerId, {
    maxFps: 6
  });
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(
    postCalls.filter((call) => call.url.endsWith('/scrcpy/attach')).length,
    2
  );

  blockedAttachSerials.delete(serial);
  blockedAttachResolvers.get(serial)?.();
  blockedAttachResolvers.delete(serial);
  await replacement;

  const attachCalls = postCalls.filter((call) =>
    call.url.endsWith('/scrcpy/attach')
  );
  assert.deepEqual(attachCalls.at(-1)?.payload, {
    viewer_id: viewerId,
    max_fps: 6
  });

  heartbeatFailuresRemaining.delete(serial);
  await stream.detachScrcpyStream(serial, viewerId);
});
