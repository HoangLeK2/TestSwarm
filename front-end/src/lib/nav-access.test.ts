import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  filterNavItemsByAccess,
  canUseAdminConsole,
  filterNavItemsByRole,
  normalizeNavOrgRole,
  normalizeNavUserRole
} from './nav-access.ts';
import { createPermissionChecker, identityFromSession } from './rbac/engine.ts';
import type { NavItem } from '../types/index.ts';

test('normalizeNavUserRole defaults unknown to operator', () => {
  assert.equal(normalizeNavUserRole(undefined), 'operator');
  assert.equal(normalizeNavUserRole('admin'), 'operator');
  assert.equal(normalizeNavUserRole('superadmin'), 'superadmin');
});

test('normalizeNavOrgRole keeps only known organization roles', () => {
  assert.equal(normalizeNavOrgRole(undefined), null);
  assert.equal(normalizeNavOrgRole('admin'), 'admin');
  assert.equal(normalizeNavOrgRole('owner'), 'owner');
  assert.equal(normalizeNavOrgRole('superadmin'), null);
});

test('filterNavItemsByRole hides superadmin-only leaves for operators', () => {
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
  const filtered = filterNavItemsByRole(items, 'operator');
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

test('filterNavItemsByAccess lets workspace admins use operations and admin console', () => {
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'admin' })
  );
  const items: NavItem[] = [
    {
      title: 'Daily',
      type: 'group',
      items: [
        {
          title: 'Device list',
          url: '/dashboard/device-farm',
          permission: { object: 'devices', action: 'read' }
        }
      ]
    },
    {
      title: 'Admin',
      type: 'group',
      items: [
        {
          title: 'Admin dashboard',
          url: '/dashboard/admin',
          permission: { object: 'organizations', action: 'read' },
          adminConsoleOnly: true
        },
        {
          title: 'Device operations',
          url: '/dashboard/device-farm/manage',
          permission: { object: 'devices', action: 'read' }
        }
      ]
    }
  ];

  const filtered = filterNavItemsByAccess(items, {
    userRole: 'operator',
    orgRole: 'admin',
    can: checker.can.bind(checker)
  });

  assert.equal(filtered.length, 2);
  assert.equal(filtered[0]?.title, 'Daily');
  assert.equal(filtered[0]?.items?.[0]?.url, '/dashboard/device-farm');
  assert.equal(filtered[1]?.title, 'Admin');
  assert.equal(filtered[1]?.items?.length, 2);
  assert.equal(filtered[1]?.items?.[0]?.url, '/dashboard/admin');
  assert.equal(filtered[1]?.items?.[1]?.url, '/dashboard/device-farm/manage');
});

test('workspace admins cannot access superadmin-only workspace admin account console', () => {
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'admin' })
  );
  const items: NavItem[] = [
    {
      title: 'Admin',
      type: 'group',
      items: [
        {
          title: 'Workspace admin',
          url: '/dashboard/admin/workspace-admins',
          roles: ['superadmin'],
          permission: { object: 'organizations', action: 'manage' },
          adminConsoleOnly: true
        }
      ]
    }
  ];

  const filtered = filterNavItemsByAccess(items, {
    userRole: 'operator',
    orgRole: 'admin',
    can: checker.can.bind(checker)
  });

  assert.equal(filtered.length, 0);
});

test('filterNavItemsByAccess keeps normal navigation but hides admin console leaves for owners', () => {
  const checker = createPermissionChecker(
    identityFromSession({ role: 'operator', orgRole: 'owner' })
  );
  const items: NavItem[] = [
    {
      title: 'Daily',
      type: 'group',
      items: [
        {
          title: 'Device list',
          url: '/dashboard/device-farm',
          permission: { object: 'devices', action: 'read' }
        }
      ]
    },
    {
      title: 'Admin',
      type: 'group',
      items: [
        {
          title: 'Admin dashboard',
          url: '/dashboard/admin',
          permission: { object: 'organizations', action: 'read' },
          adminConsoleOnly: true
        }
      ]
    }
  ];

  const filtered = filterNavItemsByAccess(items, {
    userRole: 'operator',
    orgRole: 'owner',
    can: checker.can.bind(checker)
  });

  assert.equal(filtered.length, 1);
  assert.equal(filtered[0]?.title, 'Daily');
  assert.equal(filtered[0]?.items?.[0]?.url, '/dashboard/device-farm');
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
  const mcpRouteRule =
    routeRules.match(/\{\s*prefix:\s*ROUTES\.MCP\.ROOT,[\s\S]*?\n\s*\}/)?.[0] ??
    '';
  const mcpNavItem =
    navConfig.match(/\{\s*titleKey:\s*'mcp_tokens',[\s\S]*?\n\s*\}/)?.[0] ?? '';
  const mainNav =
    navConfig.match(
      /export const DASHBOARD_MAIN_NAV_GROUPS = \[[\s\S]*?\] as const;/
    )?.[0] ?? '';

  assert.match(
    mcpRouteRule,
    /permission:\s*\{\s*object:\s*'mcp',\s*action:\s*'read'\s*\}/
  );
  assert.doesNotMatch(mcpRouteRule, /roles:\s*\['superadmin'\]/);
  assert.match(
    mcpNavItem,
    /permission:\s*\{\s*object:\s*'mcp',\s*action:\s*'read'\s*\}/
  );
  assert.match(mcpNavItem, /url:\s*ROUTES\.MCP\.ROOT/);
  assert.doesNotMatch(mainNav, /titleKey:\s*'mcp_tokens'/);
  assert.doesNotMatch(navConfig, /titleKey:\s*'mcp_agent_tools'/);
  assert.doesNotMatch(mcpNavItem, /roles:\s*\['superadmin'\]/);
  assert.equal(ownerChecker.can('mcp', 'manage'), true);
  assert.equal(memberChecker.can('mcp', 'manage'), false);
});

test('filterNavItemsByRole hides superadmin-only admin leaves for operators', () => {
  const items: NavItem[] = [
    {
      title: 'Admin',
      type: 'group',
      items: [
        {
          title: 'User admin',
          url: '/dashboard/admin/users',
          roles: ['superadmin']
        }
      ]
    }
  ];
  const filtered = filterNavItemsByRole(items, 'operator');
  assert.equal(filtered.length, 0);
});

test('filterNavItemsByRole keeps superadmin-only leaves for superadmins', () => {
  const items: NavItem[] = [
    {
      title: 'Admin',
      type: 'group',
      items: [
        {
          title: 'User admin',
          url: '/dashboard/admin/users',
          roles: ['superadmin']
        }
      ]
    }
  ];
  const filtered = filterNavItemsByRole(items, 'superadmin');
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0]?.items?.length, 1);
});

test('workspace admin account route and nav are superadmin-only', () => {
  const routeRules = readFileSync(
    new URL('./rbac/route-permissions.ts', import.meta.url),
    'utf8'
  );
  const navConfig = readFileSync(
    new URL('../config/dashboard-nav.ts', import.meta.url),
    'utf8'
  );
  const workspaceAdminRouteRule =
    routeRules.match(
      /\{\s*prefix:\s*ROUTES\.ADMIN\.WORKSPACE_ADMINS,[\s\S]*?\n\s*\}/
    )?.[0] ?? '';
  const workspaceAdminNavItem =
    navConfig.match(
      /\{\s*titleKey:\s*'admin_workspace_admins',[\s\S]*?\n\s*\}/
    )?.[0] ?? '';

  assert.match(workspaceAdminRouteRule, /roles:\s*\['superadmin'\]/);
  assert.match(workspaceAdminNavItem, /roles:\s*\['superadmin'\]/);
});

test('admin sidebar exposes workspace accounts and collected results', () => {
  const routeRules = readFileSync(
    new URL('./rbac/route-permissions.ts', import.meta.url),
    'utf8'
  );
  const navConfig = readFileSync(
    new URL('../config/dashboard-nav.ts', import.meta.url),
    'utf8'
  );
  const adminAccountsNavItem =
    navConfig.match(/\{\s*titleKey:\s*'admin_accounts',[\s\S]*?\n\s*\}/)?.[0] ??
    '';
  const adminContentNavItem =
    navConfig.match(/\{\s*titleKey:\s*'admin_content',[\s\S]*?\n\s*\}/)?.[0] ??
    '';
  const adminAccountsRouteRule =
    routeRules.match(
      /\{\s*prefix:\s*ROUTES\.ADMIN\.ACCOUNTS,[\s\S]*?\n\s*\}/
    )?.[0] ?? '';
  const adminContentRouteRule =
    routeRules.match(
      /\{\s*prefix:\s*ROUTES\.ADMIN\.CONTENT,[\s\S]*?\n\s*\}/
    )?.[0] ?? '';

  assert.match(adminAccountsNavItem, /url:\s*ROUTES\.ADMIN\.ACCOUNTS/);
  assert.match(
    adminAccountsNavItem,
    /permission:\s*\{\s*object:\s*'accounts',\s*action:\s*'read'\s*\}/
  );
  assert.match(adminContentNavItem, /url:\s*ROUTES\.ADMIN\.CONTENT/);
  assert.match(
    adminContentNavItem,
    /permission:\s*\{\s*object:\s*'content',\s*action:\s*'read'\s*\}/
  );
  assert.match(adminAccountsRouteRule, /orgRoles:\s*\['admin'\]/);
  assert.match(adminContentRouteRule, /orgRoles:\s*\['admin'\]/);
});

test('main sidebar exposes device management for device owners', () => {
  const routeRules = readFileSync(
    new URL('./rbac/route-permissions.ts', import.meta.url),
    'utf8'
  );
  const navConfig = readFileSync(
    new URL('../config/dashboard-nav.ts', import.meta.url),
    'utf8'
  );
  const devicesManageNavItem =
    navConfig.match(/\{\s*titleKey:\s*'devices_manage',[\s\S]*?\n\s*\}/)?.[0] ??
    '';
  const devicesManageRouteRule =
    routeRules.match(
      /\{\s*prefix:\s*ROUTES\.DEVICES\.MANAGE,[\s\S]*?\n\s*\}/
    )?.[0] ?? '';

  assert.match(devicesManageNavItem, /url:\s*ROUTES\.DEVICES\.MANAGE/);
  assert.match(
    devicesManageNavItem,
    /permission:\s*\{\s*object:\s*'devices',\s*action:\s*'manage'\s*\}/
  );
  assert.doesNotMatch(devicesManageNavItem, /adminConsoleOnly:\s*true/);
  assert.match(
    devicesManageRouteRule,
    /permission:\s*\{\s*object:\s*'devices',\s*action:\s*'manage'\s*\}/
  );
  assert.doesNotMatch(devicesManageRouteRule, /orgRoles:/);
});

test('workspace access route and nav require organization management', () => {
  const routeRules = readFileSync(
    new URL('./rbac/route-permissions.ts', import.meta.url),
    'utf8'
  );
  const navConfig = readFileSync(
    new URL('../config/dashboard-nav.ts', import.meta.url),
    'utf8'
  );
  const routeRule =
    routeRules.match(
      /\{\s*prefix:\s*ROUTES\.ADMIN\.WORKSPACE_ACCESS,[\s\S]*?\n\s*\}/
    )?.[0] ?? '';
  const navItem =
    navConfig.match(
      /\{\s*titleKey:\s*'admin_workspace_access',[\s\S]*?\n\s*\}/
    )?.[0] ?? '';

  assert.match(routeRule, /object:\s*'organizations',\s*action:\s*'manage'/);
  assert.match(routeRule, /orgRoles:\s*\['admin'\]/);
  assert.match(navItem, /url:\s*ROUTES\.ADMIN\.WORKSPACE_ACCESS/);
  assert.match(navItem, /object:\s*'organizations',\s*action:\s*'manage'/);
});

test('canUseAdminConsole covers workspace admins, not plain members', () => {
  assert.equal(
    canUseAdminConsole({ userRole: 'operator', orgRole: 'admin' }),
    true
  );
  assert.equal(
    canUseAdminConsole({ userRole: 'superadmin', orgRole: null }),
    true
  );
  assert.equal(
    canUseAdminConsole({ userRole: 'operator', orgRole: 'owner' }),
    false
  );
  assert.equal(
    canUseAdminConsole({ userRole: 'operator', orgRole: null }),
    false
  );
});

test('login lands an admin on the console instead of the workspace', () => {
  const hook = readFileSync(
    new URL('../features/auth/hooks/use-login.ts', import.meta.url),
    'utf8'
  );
  assert.match(hook, /canUseAdminConsole\(/);
  assert.match(hook, /\?\s*ROUTES\.ADMIN\.ROOT/);
  assert.match(hook, /router\.push\(returnTo \|\| home\)/);
});
