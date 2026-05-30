'use client';

import { useMemo } from 'react';
import {
  usePermissionContext,
  type PermissionContextValue
} from '../providers/permission-provider';
import type { PermissionAction, PermissionObject } from '@/lib/rbac';
import type { ResourcePermissionFlags } from '../types/resource-permissions';

export type { ResourcePermissionFlags } from '../types/resource-permissions';

export function useCan(): Pick<
  PermissionContextValue,
  'can' | 'canAny' | 'canAll' | 'ready'
> {
  const ctx = usePermissionContext();
  return {
    can: ctx.can,
    canAny: ctx.canAny,
    canAll: ctx.canAll,
    ready: ctx.ready
  };
}

export function usePermission(
  object: PermissionObject,
  action: PermissionAction
): boolean {
  const { can, ready } = usePermissionContext();
  if (!ready) return false;
  return can(object, action);
}

/** Convenience bundle for CRUD-style UI gates on one resource. */
export function useResourcePermissions(object: PermissionObject) {
  const { can, ready } = useCan();

  return useMemo(
    (): ResourcePermissionFlags => ({
      ready,
      canRead: can(object, 'read'),
      canCreate: can(object, 'create'),
      canUpdate: can(object, 'update'),
      canDelete: can(object, 'delete'),
      canExecute: can(object, 'execute'),
      canManage: can(object, 'manage')
    }),
    [can, object, ready]
  );
}
