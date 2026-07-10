import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_CUSTOM_PARENT_POST_ID_VAR,
  parentPostIdVarForMode
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './extract-parent-mode.ts';

test('custom parent mode stays selected when no variable was entered yet', () => {
  assert.equal(
    parentPostIdVarForMode('custom', ''),
    DEFAULT_CUSTOM_PARENT_POST_ID_VAR
  );
});

test('custom parent mode preserves an existing variable', () => {
  assert.equal(parentPostIdVarForMode('custom', 'parent_pid'), 'parent_pid');
});

test('auto parent mode removes the custom variable', () => {
  assert.equal(parentPostIdVarForMode('auto', 'parent_pid'), undefined);
});
