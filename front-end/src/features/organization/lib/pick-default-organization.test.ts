import assert from 'node:assert/strict';
import test from 'node:test';

import type { ProtoOrganization } from '../../device-farm/services/client.ts';
import {
  pickDefaultOrganization,
  reconcileCurrentOrganization
} from './pick-default-organization.ts';

function org(
  id: string,
  businessName: string,
  businessEmail?: string
): ProtoOrganization {
  return {
    id,
    businessName,
    businessEmail: businessEmail ?? null,
    businessLogo: null
  };
}

test('pickDefaultOrganization prefers defaultOrgId over stored personal workspace', () => {
  const orgs = [
    org('team', "Hoang Le's Workspace", 'dev@gmail.com'),
    org('mine', "Hoang Le's Workspace", 'guest@gmail.com')
  ];
  const picked = pickDefaultOrganization(orgs, 'mine', {
    preferredOrgId: 'team',
    userEmail: 'guest@gmail.com'
  });
  assert.equal(picked.id, 'team');
});

test('pickDefaultOrganization prefers collaboration org when no defaultOrgId', () => {
  const orgs = [
    org('team', "Hoang Le's Workspace", 'dev@gmail.com'),
    org('mine', "Hoang Le's Workspace", 'guest@gmail.com')
  ];
  const picked = pickDefaultOrganization(orgs, 'mine', {
    userEmail: 'guest@gmail.com'
  });
  assert.equal(picked.id, 'team');
});

test('reconcileCurrentOrganization keeps an explicit workspace switch', () => {
  const orgs = [
    org('default', "Hoang Le's Workspace", 'dev@gmail.com'),
    org('selected', 'Device Farm Templates', 'templates@gmail.com')
  ];

  const picked = reconcileCurrentOrganization(orgs, orgs[1], 'selected', {
    preferredOrgId: 'default',
    userEmail: 'dev@gmail.com'
  });

  assert.equal(picked.id, 'selected');
});
