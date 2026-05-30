import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  deriveSessionOwnerType,
  resolveSessionUserId
} from './session-owner.ts';

describe('session-owner', () => {
  it('deriveSessionOwnerType matches backend matrix', () => {
    assert.equal(deriveSessionOwnerType('abc', 'user-1'), 'user');
    assert.equal(deriveSessionOwnerType('exec:1'), 'execution');
    assert.equal(deriveSessionOwnerType('camp:1'), 'campaign');
    assert.equal(deriveSessionOwnerType('sys:1'), 'system');
    assert.equal(deriveSessionOwnerType('random'), 'unknown');
  });

  it('resolveSessionUserId reads payload fields', () => {
    assert.equal(resolveSessionUserId({ owner_user_id: 'u1' }), 'u1');
    assert.equal(resolveSessionUserId({ user_id: 'u2' }), 'u2');
    assert.equal(resolveSessionUserId({ owner_user_id: '  ' }), null);
    assert.equal(resolveSessionUserId(null), null);
  });
});
