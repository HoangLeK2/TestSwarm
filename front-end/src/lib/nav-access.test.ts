import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
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
  assert.equal(
    filtered[0]?.items?.[0]?.url,
    '/dashboard/settings/organization'
  );
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

test('MCP token settings route uses RBAC and stays out of tools navigation', () => {
  const ownerChecker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'owner' })
  );
  const memberChecker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'member' })
  );

  const routeRules = readFileSync(
    new URL('./rbac/route-permissions.ts', import.meta.url),
    'utf8'
  );
  const navConfig = readFileSync(
    new URL('../config/dashboard-nav.ts', import.meta.url),
    'utf8'
  );
  const mcpRouteRule = routeRules.match(
    /\{\s*prefix:\s*ROUTES\.MCP\.ROOT,[\s\S]*?\n\s*\}/
  )?.[0] ?? '';
  const mcpNavItem = navConfig.match(
    /\{\s*titleKey:\s*'mcp_tokens',[\s\S]*?\n\s*\}/
  )?.[0] ?? '';
  const mainNav = navConfig.match(
    /export const DASHBOARD_MAIN_NAV_GROUPS = \[[\s\S]*?\] as const;/
  )?.[0] ?? '';

  assert.match(mcpRouteRule, /permission:\s*\{\s*object:\s*'mcp',\s*action:\s*'read'\s*\}/);
  assert.doesNotMatch(mcpRouteRule, /roles:\s*\['superadmin'\]/);
  assert.match(mcpNavItem, /permission:\s*\{\s*object:\s*'mcp',\s*action:\s*'read'\s*\}/);
  assert.match(mcpNavItem, /url:\s*ROUTES\.MCP\.ROOT/);
  assert.doesNotMatch(mainNav, /titleKey:\s*'mcp_tokens'/);
  assert.doesNotMatch(navConfig, /titleKey:\s*'mcp_agent_tools'/);
  assert.doesNotMatch(mcpNavItem, /roles:\s*\['superadmin'\]/);
  assert.equal(ownerChecker.can('mcp', 'manage'), true);
  assert.equal(memberChecker.can('mcp', 'manage'), false);
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
