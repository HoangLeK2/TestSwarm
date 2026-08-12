import assert from 'node:assert/strict';
import test from 'node:test';
import { ACCOUNTS_PAGE_LIMIT } from '../lib/account-query';

test('account pickers stay within the backend list limit', () => {
  assert.equal(ACCOUNTS_PAGE_LIMIT, 200);
});
