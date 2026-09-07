import type { NavItem } from '@/types';
import type { PermissionChecker } from '@/lib/rbac';
import type { OrgRole, PermissionRequirement } from '@/lib/rbac/types';

/** Platform navigation role. Workspace admin comes from RBAC permissions. */
export type NavUserRole = 'superadmin' | 'operator';

export function normalizeNavUserRole(
  role: string | null | undefined
): NavUserRole {
  if (role === 'superadmin') return 'superadmin';
  return 'operator';
}

export function isSuperadminRole(role: string | null | undefined): boolean {
  return normalizeNavUserRole(role) === 'superadmin';
}

export function normalizeNavOrgRole(
  role: string | null | undefined
): OrgRole | null {
  if (role === 'owner') return 'owner';
  if (role === 'admin') return 'admin';
  if (role === 'member') return 'member';
  if (role === 'supervisor') return 'supervisor';
  return null;
}

export type NavAccessContext = {
  userRole: NavUserRole;
  orgRole?: OrgRole | null;
  can: PermissionChecker['can'];
};

/** Who the admin console belongs to. Also decides where login lands. */
export function canUseAdminConsole(
  ctx: Pick<NavAccessContext, 'userRole' | 'orgRole'>
): boolean {
  return ctx.userRole === 'superadmin' || ctx.orgRole === 'admin';
}

function canSeeNavItem(item: NavItem, ctx: NavAccessContext): boolean {
  if (item.roles?.length) {
    if (!item.roles.includes(ctx.userRole)) return false;
  }

  if (item.adminConsoleOnly && !canUseAdminConsole(ctx)) return false;

  if (item.permission) {
    return ctx.can(item.permission.object, item.permission.action);
  }

  return true;
}

/**
 * Filters nav tree by optional `roles` and RBAC `permission` on each item.
 * Empty groups are removed.
 */
export function filterNavItemsByAccess(
  items: NavItem[],
  ctx: NavAccessContext
): NavItem[] {
  const out: NavItem[] = [];

  for (const item of items) {
    if (item.type === 'divider') {
      out.push(item);
      continue;
    }

    if (item.items?.length) {
      const children = filterNavItemsByAccess(item.items, ctx);
      if (children.length === 0) continue;
      if (!canSeeNavItem(item, ctx) && item.type !== 'group') continue;
      out.push({ ...item, items: children });
      continue;
    }

    if (!canSeeNavItem(item, ctx)) continue;
    out.push(item);
  }

  return out;
}

/** @deprecated Use filterNavItemsByAccess with PermissionChecker. */
export function filterNavItemsByRole(
  items: NavItem[],
  userRole: NavUserRole
): NavItem[] {
  return filterNavItemsByAccess(items, {
    userRole,
    can: () => true
  });
}

export type { PermissionRequirement };
