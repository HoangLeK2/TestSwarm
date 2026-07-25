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
    const heartbeatMatch = url.match(/\/devices\/([^/]+)\/scrcpy\/heartbeat/);
    const heartbeatSerial = heartbeatMatch?.[1];
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

test('control screen attach uses normal retry policy and payload', async () => {
  const stream = await loadScrcpyStream();
  postCalls.length = 0;

  await stream.attachScrcpyStream('serial one', 'device-screen:viewer-1');

  assert.equal(postCalls.length, 1);
  assert.equal(postCalls[0]?.url, '/devices/serial%20one/scrcpy/attach');
  assert.deepEqual(postCalls[0]?.payload, {
    viewer_id: 'device-screen:viewer-1'
  });
  assert.deepEqual(postCalls[0]?.config, {
    timeout: 10_000,
    _skip429Retry: false
  });
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
  assert.deepEqual(postCalls[0]?.config, {
    timeout: 10_000,
    _skip429Retry: true
  });
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
