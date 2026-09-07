import assert from 'node:assert/strict';
import test from 'node:test';

import {
  clearPermissionCheckerCache,
  createPermissionChecker,
  identityFromSession,
  isSuperadminIdentity
} from './engine.ts';

test('createPermissionChecker lets workspace admins operate assigned workspaces', () => {
  clearPermissionCheckerCache();
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'admin' })
  );
  assert.equal(checker.can('devices', 'read'), true);
  assert.equal(checker.can('devices', 'manage'), true);
  assert.equal(checker.can('devices', 'create'), true);
  assert.equal(checker.can('devices', 'execute'), true);
  assert.equal(checker.can('organizations', 'create'), true);
  assert.equal(checker.can('organizations', 'update'), true);
  assert.equal(checker.can('organizations', 'delete'), true);
  assert.equal(checker.can('relay-agents', 'manage'), true);
  assert.equal(checker.can('analytics', 'read'), true);
  assert.equal(checker.can('campaigns', 'create'), true);
  assert.equal(checker.can('campaigns', 'execute'), true);
  assert.equal(checker.can('accounts', 'manage'), true);
  assert.equal(checker.can('schedules', 'execute'), true);
  assert.equal(checker.can('device-groups', 'manage'), true);
  assert.equal(checker.can('scenarios', 'update'), true);
});

test('createPermissionChecker ignores legacy platform admin role', () => {
  clearPermissionCheckerCache();
  const checker = createPermissionChecker(
    identityFromSession({ role: 'admin' })
  );
  assert.equal(checker.can('organizations', 'read'), true);
  assert.equal(checker.can('organizations', 'manage'), false);
  assert.equal(checker.can('devices', 'manage'), false);
});

test('createPermissionChecker allows superadmin all permissions', () => {
  clearPermissionCheckerCache();
  const checker = createPermissionChecker(
    identityFromSession({ role: 'superadmin' })
  );
  assert.equal(checker.can('executions', 'execute'), true);
  assert.equal(
    isSuperadminIdentity(identityFromSession({ role: 'superadmin' })),
    true
  );
});

test('createPermissionChecker denies operator user management', () => {
  clearPermissionCheckerCache();
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator' })
  );
  assert.equal(checker.can('organizations', 'read'), true);
  assert.equal(checker.can('organizations', 'update'), false);
});

test('createPermissionChecker allows owner org management', () => {
  clearPermissionCheckerCache();
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'owner' })
  );
  assert.equal(checker.can('organizations', 'read'), true);
  assert.equal(checker.can('organizations', 'update'), true);
  assert.equal(checker.can('organizations', 'manage'), true);
});

test('createPermissionChecker denies member org management', () => {
  clearPermissionCheckerCache();
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'member' })
  );
  assert.equal(checker.can('organizations', 'read'), true);
  assert.equal(checker.can('organizations', 'update'), false);
});

test('createPermissionChecker allows member device read only', () => {
  clearPermissionCheckerCache();
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'member' })
  );
  assert.equal(checker.can('devices', 'read'), true);
  assert.equal(checker.can('devices', 'create'), false);
  assert.equal(checker.can('devices', 'execute'), false);
});

test('createPermissionChecker allows owner device management', () => {
  clearPermissionCheckerCache();
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'owner' })
  );
  assert.equal(checker.can('devices', 'create'), true);
  assert.equal(checker.can('devices', 'execute'), true);
});

test('createPermissionChecker allows member campaign read only', () => {
  clearPermissionCheckerCache();
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'member' })
  );
  assert.equal(checker.can('campaigns', 'read'), true);
  assert.equal(checker.can('campaigns', 'create'), false);
});

test('createPermissionChecker allows owner campaign management', () => {
  clearPermissionCheckerCache();
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'owner' })
  );
  assert.equal(checker.can('campaigns', 'create'), true);
  assert.equal(checker.can('campaigns', 'execute'), true);
});

test('createPermissionChecker memoizes by role set', () => {
  clearPermissionCheckerCache();
  const identity = identityFromSession({ role: 'operator', orgRole: 'owner' });
  const a = createPermissionChecker(identity);
  const b = createPermissionChecker(identity);
  assert.equal(a, b);
});

test('createPermissionChecker allows supervisor operational access', () => {
  clearPermissionCheckerCache();
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'supervisor' })
  );
  assert.equal(checker.can('organizations', 'read'), true);
  assert.equal(checker.can('organizations', 'update'), false);
  assert.equal(checker.can('devices', 'read'), true);
  assert.equal(checker.can('devices', 'execute'), true);
  assert.equal(checker.can('devices', 'create'), true);
  assert.equal(checker.can('devices', 'update'), false);
  assert.equal(checker.can('campaigns', 'execute'), true);
  assert.equal(checker.can('campaigns', 'create'), true);
  assert.equal(checker.can('campaigns', 'update'), true);
  assert.equal(checker.can('campaigns', 'delete'), false);
  assert.equal(checker.can('executions', 'create'), true);
  assert.equal(checker.can('executions', 'delete'), false);
});

test('createPermissionChecker keeps supervisor read-only on templates', () => {
  clearPermissionCheckerCache();
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'supervisor' })
  );
  assert.equal(checker.can('scenario-templates', 'read'), true);
  assert.equal(checker.can('scenario-templates', 'create'), false);
});
