import assert from 'node:assert/strict';
import test from 'node:test';

import { formatOrgDisplayName } from './org-name.ts';

test('formatOrgDisplayName returns trimmed name when present', () => {
  assert.equal(
    formatOrgDisplayName("  Hoang Le's Workspace  "),
    "Hoang Le's Workspace"
  );
});

test('formatOrgDisplayName returns fallback for empty or missing name', () => {
  assert.equal(formatOrgDisplayName('', '—'), '—');
  assert.equal(formatOrgDisplayName(null, 'N/A'), 'N/A');
  assert.equal(formatOrgDisplayName('   ', '—'), '—');
});
