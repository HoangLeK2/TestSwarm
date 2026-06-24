import assert from 'node:assert/strict';
import test from 'node:test';

import {
  computeLiveInputDeltas,
  normalizeLiveInputText
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './live-input-delta.ts';

test('computeLiveInputDeltas returns empty when unchanged', () => {
  assert.deepEqual(computeLiveInputDeltas('abc', 'abc'), []);
});

test('computeLiveInputDeltas appends suffix', () => {
  assert.deepEqual(computeLiveInputDeltas('open', 'openclaw'), [
    { kind: 'append', text: 'claw' }
  ]);
});

test('computeLiveInputDeltas deletes trailing chars', () => {
  assert.deepEqual(computeLiveInputDeltas('openclaw', 'open'), [
    { kind: 'delete', count: 4 }
  ]);
});

test('computeLiveInputDeltas resets on paste or middle edit', () => {
  assert.deepEqual(computeLiveInputDeltas('abc', 'xyz'), [
    { kind: 'delete', count: 3 },
    { kind: 'reset_append', text: 'xyz' }
  ]);
});

test('normalizeLiveInputText normalizes vietnamese to NFC before diffing', () => {
  const nfd = 'e\u0301'; // é as e + combining acute
  const nfc = '\u00e9';
  assert.equal(normalizeLiveInputText(nfd), nfc);
  assert.deepEqual(computeLiveInputDeltas('', nfd), [
    { kind: 'append', text: nfc }
  ]);
});
