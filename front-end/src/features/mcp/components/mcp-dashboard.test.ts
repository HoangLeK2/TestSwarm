import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('./mcp-dashboard.tsx', import.meta.url), 'utf8');

test('MCP token dialog creates user-scoped tokens without scope controls', () => {
  assert.match(source, /scope_type:\s*'user'/);
  assert.doesNotMatch(source, /scopeType/);
  assert.doesNotMatch(source, /scopeRef/);
  assert.doesNotMatch(source, /SelectItem value='device'/);
  assert.doesNotMatch(source, /SelectItem value='user'/);
  assert.doesNotMatch(source, /scope_ref:/);
});

test('MCP dashboard exposes tokens and audit only', () => {
  assert.doesNotMatch(source, /getMcpTools/);
  assert.doesNotMatch(source, /tabs\.tools/);
  assert.doesNotMatch(source, /value='tools'/);
  assert.match(source, /tabs\.tokens/);
  assert.match(source, /tabs\.audit/);
});

test('MCP dashboard does not show preview banner', () => {
  assert.doesNotMatch(source, /PreviewBanner/);
  assert.doesNotMatch(source, /previewTitle/);
});
