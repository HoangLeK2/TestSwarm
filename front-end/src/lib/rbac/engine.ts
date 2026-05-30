import type {
  PermissionAction,
  PermissionObject,
  OrgRole,
  PermissionChecker,
  PermissionRequirement,
  PlatformRole,
  RbacIdentity
} from './types';

/** Mirrors device_farm/api/auth/rbac_policy.csv (p, role, dom, obj, act). */
type RbacPolicyRow = {
  role: string;
  object: PermissionObject;
  actions: readonly PermissionAction[];
};

const FULL_ACCESS: readonly PermissionAction[] = [
  'read',
  'create',
  'update',
  'delete',
  'execute',
  'manage'
];

const READ_ONLY: readonly PermissionAction[] = ['read'];

const EXECUTE: readonly PermissionAction[] = ['read', 'execute'];

const EXECUTE_WITH_CREATE: readonly PermissionAction[] = [
  'read',
  'create',
  'execute'
];

const EXECUTE_WITH_CREATE_UPDATE: readonly PermissionAction[] = [
  'read',
  'create',
  'update',
  'execute'
];

const MANAGE: readonly PermissionAction[] = [
  'read',
  'create',
  'update',
  'delete',
  'execute',
  'manage'
];

/** Static policy table — keep in sync with device_farm/api/auth/rbac_policy.csv */
const RBAC_POLICIES: readonly RbacPolicyRow[] = [
  { role: 'superadmin', object: '*', actions: FULL_ACCESS },
  { role: 'admin', object: '*', actions: FULL_ACCESS },
  { role: 'operator', object: 'organizations', actions: ['read', 'create'] },
  { role: 'owner', object: 'organizations', actions: MANAGE },
  { role: 'member', object: 'organizations', actions: READ_ONLY },
  { role: 'operator', object: 'me', actions: READ_ONLY },
  { role: 'operator', object: 'devices', actions: READ_ONLY },
  { role: 'owner', object: 'devices', actions: MANAGE },
  { role: 'member', object: 'devices', actions: READ_ONLY },
  { role: 'operator', object: 'campaigns', actions: READ_ONLY },
  { role: 'owner', object: 'campaigns', actions: MANAGE },
  { role: 'member', object: 'campaigns', actions: READ_ONLY },
  { role: 'operator', object: 'executions', actions: READ_ONLY },
  { role: 'owner', object: 'executions', actions: MANAGE },
  { role: 'member', object: 'executions', actions: READ_ONLY },
  { role: 'operator', object: 'scenario-templates', actions: READ_ONLY },
  {
    role: 'owner',
    object: 'scenario-templates',
    actions: ['read', 'create', 'update', 'delete', 'manage']
  },
  { role: 'member', object: 'scenario-templates', actions: READ_ONLY },
  { role: 'operator', object: 'accounts', actions: READ_ONLY },
  { role: 'owner', object: 'accounts', actions: MANAGE },
  { role: 'member', object: 'accounts', actions: READ_ONLY },
  { role: 'operator', object: 'account-groups', actions: READ_ONLY },
  { role: 'owner', object: 'account-groups', actions: MANAGE },
  { role: 'member', object: 'account-groups', actions: READ_ONLY },
  { role: 'operator', object: 'device-groups', actions: READ_ONLY },
  {
    role: 'owner',
    object: 'device-groups',
    actions: ['read', 'create', 'update', 'delete', 'manage']
  },
  { role: 'member', object: 'device-groups', actions: READ_ONLY },
  { role: 'operator', object: 'schedules', actions: READ_ONLY },
  { role: 'owner', object: 'schedules', actions: MANAGE },
  { role: 'member', object: 'schedules', actions: READ_ONLY },
  { role: 'operator', object: 'relay-agents', actions: READ_ONLY },
  { role: 'owner', object: 'relay-agents', actions: MANAGE },
  { role: 'member', object: 'relay-agents', actions: READ_ONLY },
  { role: 'operator', object: 'notifications', actions: READ_ONLY },
  { role: 'owner', object: 'notifications', actions: MANAGE },
  { role: 'member', object: 'notifications', actions: READ_ONLY },
  { role: 'operator', object: 'content', actions: READ_ONLY },
  {
    role: 'owner',
    object: 'content',
    actions: ['read', 'create', 'update', 'delete', 'manage']
  },
  { role: 'member', object: 'content', actions: READ_ONLY },
  { role: 'operator', object: 'analytics', actions: READ_ONLY },
  { role: 'owner', object: 'analytics', actions: READ_ONLY },
  { role: 'member', object: 'analytics', actions: READ_ONLY },
  { role: 'supervisor', object: 'organizations', actions: READ_ONLY },
  { role: 'supervisor', object: 'me', actions: READ_ONLY },
  { role: 'supervisor', object: 'devices', actions: [...EXECUTE, 'create'] },
  { role: 'supervisor', object: 'campaigns', actions: EXECUTE_WITH_CREATE_UPDATE },
  { role: 'supervisor', object: 'executions', actions: EXECUTE_WITH_CREATE },
  { role: 'supervisor', object: 'scenario-templates', actions: READ_ONLY },
  { role: 'supervisor', object: 'accounts', actions: READ_ONLY },
  { role: 'supervisor', object: 'account-groups', actions: READ_ONLY },
  { role: 'supervisor', object: 'device-groups', actions: READ_ONLY },
  { role: 'supervisor', object: 'schedules', actions: EXECUTE },
  { role: 'supervisor', object: 'relay-agents', actions: READ_ONLY },
  { role: 'supervisor', object: 'notifications', actions: READ_ONLY },
  { role: 'supervisor', object: 'content', actions: READ_ONLY },
  { role: 'supervisor', object: 'analytics', actions: READ_ONLY }
] as const;

const checkerCache = new Map<string, PermissionChecker>();

function normalizePlatformRole(role: string | null | undefined): PlatformRole {
  if (role === 'superadmin') return 'superadmin';
  if (role === 'admin') return 'admin';
  return 'operator';
}

function normalizeOrgRole(role: string | null | undefined): OrgRole | null {
  if (role === 'owner') return 'owner';
  if (role === 'member') return 'member';
  if (role === 'supervisor') return 'supervisor';
  return null;
}

/** Same role union as device_farm/api/auth/rbac.roles_for_user. */
export function rolesForIdentity(identity: RbacIdentity): readonly string[] {
  const roles = new Set<string>([identity.role]);
  if (identity.orgRole) roles.add(identity.orgRole);
  return Array.from(roles).sort();
}

export function identityFromSession(input: {
  role?: string | null;
  orgRole?: string | null;
}): RbacIdentity {
  return {
    role: normalizePlatformRole(input.role),
    orgRole: normalizeOrgRole(input.orgRole)
  };
}

type PermissionIndex = Map<PermissionObject, Set<PermissionAction>>;

function buildPermissionIndex(roles: readonly string[]): PermissionIndex {
  const index: PermissionIndex = new Map();

  for (const policy of RBAC_POLICIES) {
    if (!roles.includes(policy.role)) continue;

    let actions = index.get(policy.object);
    if (!actions) {
      actions = new Set();
      index.set(policy.object, actions);
    }
    for (const action of policy.actions) {
      actions.add(action);
    }
  }

  return index;
}

function hasAction(
  index: PermissionIndex,
  object: PermissionObject,
  action: PermissionAction
): boolean {
  const wildcard = index.get('*');
  if (wildcard?.has(action)) return true;

  const objectActions = index.get(object);
  return objectActions?.has(action) ?? false;
}

function cacheKey(roles: readonly string[]): string {
  return roles.join('|');
}

/** Memoized checker — O(1) lookups after first build for a role set. */
export function createPermissionChecker(identity: RbacIdentity): PermissionChecker {
  const roles = rolesForIdentity(identity);
  const key = cacheKey(roles);
  const cached = checkerCache.get(key);
  if (cached) return cached;

  const index = buildPermissionIndex(roles);

  const checker: PermissionChecker = {
    can(object, action) {
      return hasAction(index, object, action);
    },
    canAny(requirements) {
      return requirements.some((req) => checker.can(req.object, req.action));
    },
    canAll(requirements) {
      return requirements.every((req) => checker.can(req.object, req.action));
    }
  };

  checkerCache.set(key, checker);
  return checker;
}

/** Test-only — clears memoized checkers between cases. */
export function clearPermissionCheckerCache(): void {
  checkerCache.clear();
}

export function isSuperadminIdentity(identity: RbacIdentity): boolean {
  return identity.role === 'superadmin';
}

export type { PermissionRequirement };
