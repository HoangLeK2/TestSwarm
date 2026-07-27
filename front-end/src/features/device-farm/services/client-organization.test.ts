import assert from 'node:assert/strict';
import test from 'node:test';

import { resolveClientOrganizationId } from './client-organization.ts';

test('request-scoped organization wins over a stale stored organization', () => {
  assert.equal(resolveClientOrganizationId('org-b', 'org-a'), 'org-b');
});

test('generated singleton falls back to the stored organization', () => {
  assert.equal(resolveClientOrganizationId(null, ' org-a '), 'org-a');
});
