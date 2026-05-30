import assert from 'node:assert/strict';
import test from 'node:test';

import {
  filterNavItemsByAccess,
  filterNavItemsByRole,
  normalizeNavUserRole
} from './nav-access.ts';
import { createPermissionChecker, identityFromSession } from './rbac/engine.ts';
import type { NavItem } from '../types/index.ts';

test('normalizeNavUserRole defaults unknown to operator', () => {
  assert.equal(normalizeNavUserRole(undefined), 'operator');
  assert.equal(normalizeNavUserRole('admin'), 'admin');
  assert.equal(normalizeNavUserRole('superadmin'), 'superadmin');
});

test('filterNavItemsByRole hides superadmin-only leaves for admins', () => {
  const items: NavItem[] = [
    {
      title: 'Settings',
      type: 'group',
      items: [
        {
          title: 'All organizations',
          url: '/dashboard/settings/organizations',
          roles: ['superadmin']
        },
        {
          title: 'Organization',
          url: '/dashboard/settings/organization'
        }
      ]
    }
  ];
  const filtered = filterNavItemsByRole(items, 'admin');
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0]?.items?.length, 1);
  assert.equal(filtered[0]?.items?.[0]?.url, '/dashboard/settings/organization');
});

test('filterNavItemsByAccess hides write-only nav for org members', () => {
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'member' })
  );
  const items: NavItem[] = [
    {
      title: 'Devices',
      type: 'group',
      items: [
        {
          title: 'Control',
          url: '/dashboard/device-farm/control',
          permission: { object: 'devices', action: 'execute' }
        },
        {
          title: 'List',
          url: '/dashboard/device-farm',
          permission: { object: 'devices', action: 'read' }
        }
      ]
    }
  ];

  const filtered = filterNavItemsByAccess(items, {
    userRole: 'operator',
    can: checker.can.bind(checker)
  });

  assert.equal(filtered.length, 1);
  assert.equal(filtered[0]?.items?.length, 1);
  assert.equal(filtered[0]?.items?.[0]?.url, '/dashboard/device-farm');
});

test('filterNavItemsByAccess shows execute nav for org supervisors', () => {
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'supervisor' })
  );
  const items: NavItem[] = [
    {
      title: 'Devices',
      type: 'group',
      items: [
        {
          title: 'Control',
          url: '/dashboard/device-farm/control',
          permission: { object: 'devices', action: 'execute' }
        },
        {
          title: 'List',
          url: '/dashboard/device-farm',
          permission: { object: 'devices', action: 'read' }
        }
      ]
    }
  ];

  const filtered = filterNavItemsByAccess(items, {
    userRole: 'operator',
    can: checker.can.bind(checker)
  });

  assert.equal(filtered.length, 1);
  assert.equal(filtered[0]?.items?.length, 2);
});

test('filterNavItemsByRole hides admin-only leaves for operators', () => {
  const items: NavItem[] = [
    {
      title: 'Admin',
      type: 'group',
      items: [
        {
          title: 'User admin',
          url: '/dashboard/admin/users',
          roles: ['admin']
        }
      ]
    }
  ];
  const filtered = filterNavItemsByRole(items, 'operator');
  assert.equal(filtered.length, 0);
});

test('filterNavItemsByRole keeps admin-only leaves for admins', () => {
  const items: NavItem[] = [
    {
      title: 'Admin',
      type: 'group',
      items: [
        {
          title: 'User admin',
          url: '/dashboard/admin/users',
          roles: ['admin']
        }
      ]
    }
  ];
  const filtered = filterNavItemsByRole(items, 'admin');
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0]?.items?.length, 1);
});
