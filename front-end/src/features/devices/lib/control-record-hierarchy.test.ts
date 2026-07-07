import assert from 'node:assert/strict';
import test from 'node:test';

import {
  needsFreshMirrorSelectorXml,
  resolveInteractionHierarchyXml
} from './control-record-hierarchy.ts';

test('interaction hierarchy uses fresh XML when available', () => {
  assert.equal(
    resolveInteractionHierarchyXml(' <hierarchy fresh="1" /> ', '<old />', {
      freshAttempted: true
    }),
    '<hierarchy fresh="1" />'
  );
});

test('interaction hierarchy does not fall back to stale cached XML after a fresh fetch was attempted', () => {
  assert.equal(
    resolveInteractionHierarchyXml(null, '<old />', { freshAttempted: true }),
    ''
  );
  assert.equal(
    resolveInteractionHierarchyXml('', '<old />', { freshAttempted: true }),
    ''
  );
});

test('interaction hierarchy may use cached XML only when no fresh fetch was attempted', () => {
  assert.equal(
    resolveInteractionHierarchyXml(null, ' <cached /> ', {
      freshAttempted: false
    }),
    '<cached />'
  );
});

test('mirror selector picks require fresh XML, coordinate-only picks do not', () => {
  assert.equal(
    needsFreshMirrorSelectorXml({
      selectorPickTarget: { stepId: 'step-1' },
      flowSelectorPickFgId: null
    }),
    true
  );
  assert.equal(
    needsFreshMirrorSelectorXml({
      selectorPickTarget: null,
      flowSelectorPickFgId: 'flow-1'
    }),
    true
  );
  assert.equal(
    needsFreshMirrorSelectorXml({
      selectorPickTarget: null,
      flowSelectorPickFgId: null
    }),
    false
  );
});
