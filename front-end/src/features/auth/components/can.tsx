'use client';

import type { ReactNode } from 'react';
import { usePermission } from '../hooks/use-permission';
import type { PermissionAction, PermissionObject } from '@/lib/rbac';

type CanProps = {
  object: PermissionObject;
  action: PermissionAction;
  children: ReactNode;
  fallback?: ReactNode;
};

/** Declarative RBAC gate — hides children when permission is denied. */
export function Can({ object, action, children, fallback = null }: CanProps) {
  const allowed = usePermission(object, action);
  return allowed ? children : fallback;
}
