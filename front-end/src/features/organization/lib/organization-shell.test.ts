import assert from 'node:assert/strict';
import test from 'node:test';

import { createPendingOrganizationShell } from './organization-shell.ts';

test('createPendingOrganizationShell uses default org id while org list is loading', () => {
  const shell = createPendingOrganizationShell({
    defaultOrgId: 'org-default',
    storedOrgId: 'org-stored',
    userEmail: 'dev1234@gmail.com'
  });

  assert.equal(shell?.id, 'org-default');
  assert.equal(shell?.businessName, 'dev1234@gmail.com');
  assert.equal(shell?.businessEmail, 'dev1234@gmail.com');
});

test('createPendingOrganizationShell falls back to stored org id', () => {
  const shell = createPendingOrganizationShell({
    defaultOrgId: null,
    storedOrgId: 'org-stored',
    userEmail: ''
  });

  assert.equal(shell?.id, 'org-stored');
  assert.equal(shell?.businessName, 'Workspace');
});

test('createPendingOrganizationShell returns null without an org id', () => {
  assert.equal(
    createPendingOrganizationShell({
      defaultOrgId: ' ',
      storedOrgId: null,
      userEmail: 'dev1234@gmail.com'
    }),
    null
  );
});
