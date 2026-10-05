import assert from 'node:assert/strict';
import test from 'node:test';

const farmApiModule = await import('@/lib/farm-api');

type FarmApiGet = (
  url: string,
  config?: { params?: Record<string, unknown> }
) => Promise<{ data: unknown }>;

const getCalls: Array<{ url: string; params: Record<string, unknown> }> = [];

(farmApiModule.farmApi as unknown as { get: FarmApiGet }).get = async (
  url,
  config
) => {
  getCalls.push({ url, params: config?.params ?? {} });
  return { data: { items: [], total: 0, limit: 50, offset: 0 } };
};

const { contentApi } = await import('./api.ts');

test('contentApi.list sends run_id as execution_id for backend filtering', async () => {
  getCalls.length = 0;

  await contentApi.list({
    collection: 'crawl',
    content_type: 'ig_media',
    search: 'openclaw',
    run_id: 'exec-123',
    limit: 25,
    offset: 50
  });

  assert.equal(getCalls.length, 1);
  assert.equal(getCalls[0].url, '/content');
  assert.equal(getCalls[0].params.execution_id, 'exec-123');
  assert.equal(getCalls[0].params.run_id, undefined);
});
