import type { NavItem } from '@/types';
import type { PermissionChecker } from '@/lib/rbac';
import type { PermissionRequirement } from '@/lib/rbac/types';

/** Matches device_farm UserRole (users.role check constraint). */
export type NavUserRole = 'superadmin' | 'admin' | 'operator';

export function normalizeNavUserRole(
  role: string | null | undefined
): NavUserRole {
  if (role === 'superadmin') return 'superadmin';
  if (role === 'admin') return 'admin';
  return 'operator';
}

export function isSuperadminRole(role: string | null | undefined): boolean {
  return normalizeNavUserRole(role) === 'superadmin';
}

export type NavAccessContext = {
  userRole: NavUserRole;
  can: PermissionChecker['can'];
};

function canSeeNavItem(item: NavItem, ctx: NavAccessContext): boolean {
  if (item.roles?.length) {
    if (!item.roles.includes(ctx.userRole)) return false;
  }

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
