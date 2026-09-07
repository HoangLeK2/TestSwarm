import assert from 'node:assert/strict';
import test from 'node:test';

import {
  isEditableOrganizationMemberRole,
  organizationMemberRoleLabelKey
} from './organization-member-role.ts';

test('organizationMemberRoleLabelKey keeps workspace admins distinct from staff', () => {
  assert.equal(organizationMemberRoleLabelKey('owner'), 'owner');
  assert.equal(organizationMemberRoleLabelKey('admin'), 'admin');
  assert.equal(organizationMemberRoleLabelKey('member'), 'staff');
  assert.equal(organizationMemberRoleLabelKey('supervisor'), 'supervisor');
});

test('isEditableOrganizationMemberRole only allows regular member roles', () => {
  assert.equal(isEditableOrganizationMemberRole('member'), true);
  assert.equal(isEditableOrganizationMemberRole('supervisor'), true);
  assert.equal(isEditableOrganizationMemberRole('admin'), false);
  assert.equal(isEditableOrganizationMemberRole('owner'), false);
});
