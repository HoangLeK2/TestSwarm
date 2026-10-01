import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  keywordListFromInput,
  reconcileKeywordInputDraft
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './keyword-list-input.ts';

test('keeps a typed comma while persisting parsed social keywords', () => {
  const typed = 'năm học mới,';
  const persisted = keywordListFromInput(typed);

  assert.deepEqual(persisted, ['năm học mới']);
  assert.equal(reconcileKeywordInputDraft(typed, persisted), typed);
  assert.deepEqual(keywordListFromInput(`${typed} công nghệ`), [
    'năm học mới',
    'công nghệ'
  ]);
});

test('accepts an external social keyword-list replacement', () => {
  assert.equal(
    reconcileKeywordInputDraft('năm học mới,', ['tuyển dụng', 'công nghệ']),
    'tuyển dụng, công nghệ'
  );
});

test('resets the draft when a different node has the same keyword list', () => {
  assert.equal(
    reconcileKeywordInputDraft('năm học mới,', ['năm học mới'], false),
    'năm học mới'
  );
});

test('all array-backed social keyword fields use the draft-preserving input', () => {
  const source = readFileSync(
    new URL('./step-detail-panel.tsx', import.meta.url),
    'utf8'
  );

  assert.equal(source.match(/<KeywordListTextInput/g)?.length, 9);
  assert.equal(source.match(/identity={`\${stepIdentity}:/g)?.length, 9);
});
