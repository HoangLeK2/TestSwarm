import { ROUTES } from '@/config/routes';
import type { NavUserRole } from '@/lib/nav-access';
import type { OrgRole, PermissionRequirement } from './types';

export type RouteAccessRule = {
  prefix: string;
  permission?: PermissionRequirement;
  /** Platform-role gate for surfaces outside org RBAC (e.g. global org directory). */
  roles?: readonly NavUserRole[];
  /** Organization-role gate for workspace admin surfaces; superadmin bypasses this. */
  orgRoles?: readonly OrgRole[];
};

/** Longest-prefix wins — order entries from most specific to least specific. */
export const DASHBOARD_ROUTE_ACCESS: readonly RouteAccessRule[] = [
  {
    prefix: ROUTES.ADMIN.AUDIT,
    permission: { object: 'analytics', action: 'read' },
    orgRoles: ['admin']
  },
  {
    prefix: ROUTES.ADMIN.AGENTS,
    permission: { object: 'relay-agents', action: 'read' },
    orgRoles: ['admin']
  },
  {
    prefix: ROUTES.ADMIN.DEVICES,
    permission: { object: 'devices', action: 'read' },
    orgRoles: ['admin']
  },
  {
    prefix: ROUTES.ADMIN.WORKSPACE_ADMINS,
    permission: { object: 'organizations', action: 'manage' },
    roles: ['superadmin']
  },
  {
    prefix: ROUTES.ADMIN.WORKSPACE_ACCESS,
    permission: { object: 'organizations', action: 'manage' },
    orgRoles: ['admin']
  },
  {
    prefix: ROUTES.ADMIN.ACCOUNTS,
    permission: { object: 'accounts', action: 'read' },
    orgRoles: ['admin']
  },
  {
    prefix: ROUTES.ADMIN.CONTENT,
    permission: { object: 'content', action: 'read' },
    orgRoles: ['admin']
  },
  {
    prefix: ROUTES.ADMIN.WORKSPACES,
    permission: { object: 'organizations', action: 'read' },
    orgRoles: ['admin']
  },
  {
    prefix: ROUTES.ADMIN.ROOT,
    permission: { object: 'organizations', action: 'read' },
    orgRoles: ['admin']
  },
  {
    prefix: ROUTES.DASHBOARD.ORGANIZATION_LIST,
    roles: ['superadmin']
  },
  {
    prefix: ROUTES.DASHBOARD.ORGANIZATION_MEMBER,
    permission: { object: 'organizations', action: 'read' }
  },
  {
    prefix: ROUTES.DASHBOARD.ORGANIZATION,
    permission: { object: 'organizations', action: 'read' }
  },
  {
    prefix: ROUTES.DEVICES.CONTROL_RECORD,
    permission: { object: 'devices', action: 'execute' }
  },
  {
    prefix: ROUTES.DEVICES.MANAGE,
    permission: { object: 'devices', action: 'read' },
    orgRoles: ['admin']
  },
  {
    prefix: ROUTES.DEVICES.ROOT,
    permission: { object: 'devices', action: 'read' }
  },
  {
    prefix: ROUTES.DEVICE_GROUPS.ROOT,
    permission: { object: 'device-groups', action: 'read' }
  },
  {
    prefix: ROUTES.CAMPAIGNS.ROOT,
    permission: { object: 'campaigns', action: 'read' }
  },
  {
    prefix: ROUTES.SCHEDULES.ROOT,
    permission: { object: 'schedules', action: 'read' }
  },
  {
    prefix: ROUTES.ACCOUNTS.ROOT,
    permission: { object: 'accounts', action: 'read' }
  },
  {
    prefix: ROUTES.ACCOUNT_GROUPS.ROOT,
    permission: { object: 'account-groups', action: 'read' }
  },
  {
    prefix: ROUTES.SCENARIO_TEMPLATES.ROOT,
    permission: { object: 'scenario-templates', action: 'read' }
  },
  {
    prefix: ROUTES.CONTENT.ROOT,
    permission: { object: 'content', action: 'read' }
  },
  {
    prefix: ROUTES.DASHBOARD.ACTIVITY_HISTORY.ROOT,
    permission: { object: 'analytics', action: 'read' }
  },
  {
    // Temporary: analytics rollout — superadmin platform accounts only.
    prefix: ROUTES.ANALYTICS.ROOT,
    roles: ['superadmin']
  },
  {
    prefix: ROUTES.NOTIFICATIONS.ROOT,
    permission: { object: 'notifications', action: 'read' }
  },
  {
    prefix: ROUTES.MCP.ROOT,
    permission: { object: 'mcp', action: 'read' }
  },
  {
    prefix: ROUTES.MCP.LEGACY_ROOT,
    permission: { object: 'mcp', action: 'read' }
  },
  {
    prefix: ROUTES.RELAY_AGENTS.ROOT,
    permission: { object: 'relay-agents', action: 'read' }
  }
];

export function matchDashboardRouteAccess(
  pathname: string
): RouteAccessRule | null {
  const normalized = pathname.replace(/\/+$/, '') || '/';
  let best: RouteAccessRule | null = null;

  for (const rule of DASHBOARD_ROUTE_ACCESS) {
    const prefix = rule.prefix.replace(/\/+$/, '');
    if (normalized === prefix || normalized.startsWith(`${prefix}/`)) {
      if (!best || prefix.length > best.prefix.length) {
        best = rule;
      }
    }
  }

  return best;
}
