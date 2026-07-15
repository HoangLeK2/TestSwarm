import assert from 'node:assert/strict';
import test from 'node:test';

type FarmApiPost = (
  url: string,
  payload?: unknown,
  config?: unknown
) => Promise<{ data: unknown }>;

const postCalls: Array<{ url: string; payload: unknown; config: unknown }> = [];
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
    return { data: { ok: true } };
  };
  streamModule = await import('./scrcpy-stream');
  return streamModule;
}

test('control screen attach invalidates cached H264 bootstrap frames', async () => {
  const stream = await loadScrcpyStream();
  assert.equal(
    stream.shouldClearH264CacheBeforeScrcpyAttach('device-screen:viewer-1'),
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
});
