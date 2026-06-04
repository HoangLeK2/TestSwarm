import assert from 'node:assert/strict';
import test from 'node:test';
import { blobFromExportResponse } from './parse-export-blob.ts';

function mockResponse(
  blob: Blob,
  opts?: { contentType?: string; status?: number }
) {
  return {
    data: blob,
    status: opts?.status ?? 200,
    statusText: 'OK',
    headers: { 'content-type': opts?.contentType ?? '' },
    config: {}
  };
}

test('blobFromExportResponse accepts JSON scenario export', async () => {
  const json = JSON.stringify({
    schema_version: '2.0',
    scenario: { name: 'A', body: { steps: [] } },
    checksum: 'sha256:x'
  });
  const blob = new Blob([json], { type: 'application/json' });
  const out = await blobFromExportResponse(
    mockResponse(blob, { contentType: 'application/json' }) as never,
    'json'
  );
  assert.equal(out.size, blob.size);
});

test('blobFromExportResponse rejects FastAPI error JSON on yaml export', async () => {
  const blob = new Blob([JSON.stringify({ detail: 'Not authenticated' })], {
    type: 'application/json'
  });
  await assert.rejects(
    () =>
      blobFromExportResponse(
        mockResponse(blob, { contentType: 'application/json' }) as never,
        'yaml'
      ),
    (err: Error) => err.message === 'Not authenticated'
  );
});

test('blobFromExportResponse accepts yaml export by content-type', async () => {
  const yaml = 'schema_version: "2.0"\nscenario:\n  name: A\n';
  const blob = new Blob([yaml], { type: 'application/x-yaml' });
  const out = await blobFromExportResponse(
    mockResponse(blob, { contentType: 'application/x-yaml' }) as never,
    'yaml'
  );
  assert.equal(await out.text(), yaml);
});
