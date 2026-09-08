import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// farmApi's baseURL already ends in /api. A second '/api' here produced
// /api/api/social-ext/platforms → 404 → the node editor showed every provider
// as "chưa hỗ trợ".
test('social-ext requests do not repeat the /api prefix', () => {
  const source = readFileSync(
    new URL('./social-ext-api.ts', import.meta.url),
    'utf8'
  );
  assert.equal(/farmApi\.\w+<[^>]*>\(\s*'\/api\//.test(source), false);
  assert.match(source, /'\/social-ext\/platforms'/);
  assert.match(source, /'\/social-ext\/node-catalog'/);
});
