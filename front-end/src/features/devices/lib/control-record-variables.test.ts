import assert from 'node:assert/strict';
import test from 'node:test';

import {
  collectDeclaredDeviceVarKeys,
  flattenVarDefs,
  mergeDeclaredDeviceVarKeys,
  mergeTemplateVariablesIntoEditor
} from './control-record-variables.ts';

const parseJson = (draft: string) => JSON.parse(draft || '{}');

test('flattenVarDefs converts template metadata defaults to runtime values', () => {
  assert.deepEqual(
    flattenVarDefs({
      plain: 'kept',
      group: { type: 'string', default: 'A', description: 'ignored' },
      nested: { default: 'not flattened without type' }
    }),
    {
      plain: 'kept',
      group: 'A',
      nested: { default: 'not flattened without type' }
    }
  );
});

test('mergeTemplateVariablesIntoEditor overlays flattened template values', () => {
  assert.deepEqual(
    mergeTemplateVariablesIntoEditor(
      { existing: 'old', untouched: 1 },
      { existing: { type: 'string', default: 'new' }, added: 2 }
    ),
    { existing: 'new', untouched: 1, added: 2 }
  );
});

test('collectDeclaredDeviceVarKeys only reads enabled valid JSON drafts', () => {
  assert.deepEqual(
    collectDeclaredDeviceVarKeys(
      {
        a: '{"GROUP":"x","bad-key":"hidden"}',
        b: '{"DISABLED":"no"}',
        c: '{invalid'
      },
      { a: true, b: false, c: true },
      {},
      parseJson
    ),
    ['GROUP']
  );
});

test('mergeDeclaredDeviceVarKeys appends missing keys without cloning unchanged input', () => {
  const existing = { GROUP: 'kept' };
  assert.equal(mergeDeclaredDeviceVarKeys(existing, ['GROUP']), existing);
  assert.deepEqual(mergeDeclaredDeviceVarKeys(existing, ['GROUP', 'NEW']), {
    GROUP: 'kept',
    NEW: ''
  });
});
