/** Casbin policy objects — keep in sync with device_farm/api/auth/rbac_policy.csv */
export type PermissionObject =
  | 'me'
  | 'organizations'
  | 'devices'
  | 'campaigns'
  | 'executions'
  | 'scenario-templates'
  | 'scenarios'
  | 'accounts'
  | 'account-groups'
  | 'device-groups'
  | 'schedules'
  | 'relay-agents'
  | 'notifications'
  | 'content'
  | 'analytics'
  | 'mcp'
  | '*';

export type PermissionAction =
  | 'read'
  | 'create'
  | 'update'
  | 'delete'
  | 'execute'
  | 'manage';

export type PermissionRequirement = {
  object: PermissionObject;
  action: PermissionAction;
};

/** Platform role on users.role — matches backend UserRole constraint. */
export type PlatformRole = 'superadmin' | 'admin' | 'operator';

/** Organization membership role — from GET /auth/me orgRole. */
export type OrgRole = 'owner' | 'member' | 'supervisor';

export type RbacIdentity = {
  role: PlatformRole;
  orgRole?: OrgRole | null;
};

export type PermissionChecker = {
  can: (object: PermissionObject, action: PermissionAction) => boolean;
  canAny: (requirements: readonly PermissionRequirement[]) => boolean;
  canAll: (requirements: readonly PermissionRequirement[]) => boolean;
};
