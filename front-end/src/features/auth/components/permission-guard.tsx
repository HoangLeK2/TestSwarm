'use client';

import { useEffect, type ReactNode } from 'react';
import { usePathname, useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import {
  matchDashboardRouteAccess,
  type PermissionAction,
  type PermissionObject
} from '@/lib/rbac';
import { normalizeNavUserRole } from '@/lib/nav-access';
import { useCan } from '../hooks/use-permission';
import { useUser } from '../hooks/use-auth';

type PermissionGuardProps = {
  children: ReactNode;
  object?: PermissionObject;
  action?: PermissionAction;
};

/**
 * Redirects to /403 when the caller lacks RBAC permission for the current
 * dashboard route (or an explicit object/action pair).
 */
export function PermissionGuard({
  children,
  object,
  action = 'read'
}: PermissionGuardProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, isLoading } = useUser();
  const { can, ready } = useCan();

  const rule = object ? null : matchDashboardRouteAccess(pathname);
  const requiredObject = object ?? rule?.permission?.object;
  const requiredAction = object ? action : (rule?.permission?.action ?? action);
  const requiredRoles = rule?.roles;

  const roleAllowed =
    !requiredRoles || requiredRoles.includes(normalizeNavUserRole(user?.role));

  const permissionAllowed =
    !requiredObject || can(requiredObject, requiredAction);

  const allowed = roleAllowed && permissionAllowed;

  useEffect(() => {
    if (isLoading || !ready) return;
    if (!allowed) {
      router.replace(ROUTES.ERROR.FORBIDDEN);
    }
  }, [allowed, isLoading, ready, router]);

  if (isLoading || !ready || !allowed) {
    return null;
  }

  return children;
}
