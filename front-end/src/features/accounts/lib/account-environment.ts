import type { AccountOut } from '../services/api';

export type AccountEnvironmentFlag = 'test' | 'dev' | null;

const TEST_USERNAME = /\b(test|demo|sandbox|staging)\b/i;
const TEST_EMAIL = /@(test|example)\./i;
const DEV_USERNAME = /^dev$/i;
const DEV_TAG = /\bdev\b/i;

export function detectAccountEnvironment(
  account: AccountOut
): AccountEnvironmentFlag {
  const username = String(account.username ?? '').trim();
  const displayName = String(account.display_name ?? '').trim();
  const tags = String(account.tags ?? '');
  const haystack = [username, displayName, tags].filter(Boolean).join(' ');

  if (
    DEV_USERNAME.test(username) ||
    DEV_TAG.test(tags) ||
    /\bdev\b/i.test(haystack)
  ) {
    return 'dev';
  }
  if (
    TEST_USERNAME.test(haystack) ||
    TEST_EMAIL.test(username) ||
    /@test\./i.test(username) ||
    username.toLowerCase().includes('test@')
  ) {
    return 'test';
  }
  return null;
}
