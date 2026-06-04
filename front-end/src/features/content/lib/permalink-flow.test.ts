/**
 * Client-side permalink / login-bounce flow (TC-DF-T-11-010-07).
 * Full browser E2E is not wired in CI; this covers returnTo + URL shape.
 */
import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildContentPermalink,
  consumeAuthReturnTo,
  saveAuthReturnTo
} from './permalink.ts';

test('buildContentPermalink includes locale, id, and encoded share token', () => {
  const url = buildContentPermalink(
    'https://app.example.com',
    'vi',
    'item-abc',
    'token.with.parts'
  );
  assert.equal(
    url,
    'https://app.example.com/vi/dashboard/content/item-abc?share=token.with.parts'
  );
});

test('saveAuthReturnTo and consumeAuthReturnTo round-trip once', () => {
  const originalWindow = globalThis.window;
  const originalStorage = globalThis.sessionStorage;
  const store = new Map<string, string>();

  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: {}
  });
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => {
        store.set(k, v);
      },
      removeItem: (k: string) => {
        store.delete(k);
      }
    }
  });

  try {
    store.clear();
    saveAuthReturnTo('/dashboard/content/item-1?share=abc');
    const path = consumeAuthReturnTo();
    assert.equal(path, '/dashboard/content/item-1?share=abc');
    assert.equal(consumeAuthReturnTo(), null);
  } finally {
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: originalWindow
    });
    Object.defineProperty(globalThis, 'sessionStorage', {
      configurable: true,
      value: originalStorage
    });
  }
});
