/** Snapshot of RBAC flags for one resource — pass to tables or derive via useResourcePermissions. */
export type ResourcePermissionFlags = {
  ready: boolean;
  canRead: boolean;
  canCreate: boolean;
  canUpdate: boolean;
  canDelete: boolean;
  canExecute: boolean;
  canManage: boolean;
};

export const denyResourcePermissions: ResourcePermissionFlags = {
  ready: false,
  canRead: false,
  canCreate: false,
  canUpdate: false,
  canDelete: false,
  canExecute: false,
  canManage: false
};
