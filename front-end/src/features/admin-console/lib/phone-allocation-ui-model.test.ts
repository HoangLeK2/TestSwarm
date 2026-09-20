import assert from 'node:assert/strict';
import test from 'node:test';

import {
  canAssignPhones,
  selectedWorkspaceName,
  showReturnToPoolAction
} from './phone-allocation-ui-model.ts';

const workspaces = [
  { id: 'workspace-id-1', businessName: 'Alpha Workspace' },
  { id: 'workspace-id-2', businessName: 'Beta Workspace' }
];

test('selectedWorkspaceName returns the readable workspace name', () => {
  assert.equal(
    selectedWorkspaceName(workspaces, 'workspace-id-2'),
    'Beta Workspace'
  );
});

test('selectedWorkspaceName does not fall back to showing the workspace id', () => {
  assert.equal(selectedWorkspaceName(workspaces, 'missing-workspace-id'), '');
});

test('canAssignPhones waits for both phone selection and a readable workspace target', () => {
  assert.equal(
    canAssignPhones({
      selectedCount: 0,
      targetWorkspaceId: 'workspace-id-1',
      targetWorkspaceName: 'Alpha Workspace'
    }),
    false
  );
  assert.equal(
    canAssignPhones({
      selectedCount: 1,
      targetWorkspaceId: 'workspace-id-1',
      targetWorkspaceName: ''
    }),
    false
  );
  assert.equal(
    canAssignPhones({
      selectedCount: 1,
      targetWorkspaceId: 'workspace-id-1',
      targetWorkspaceName: 'Alpha Workspace'
    }),
    true
  );
});

test('showReturnToPoolAction hides zero-count actions', () => {
  assert.equal(showReturnToPoolAction(0), false);
  assert.equal(showReturnToPoolAction(1), true);
});
