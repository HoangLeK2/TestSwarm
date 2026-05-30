'use client';

import React from 'react';
import type { SessionUser } from '../types/session-user';
import {
  createPermissionChecker,
  identityFromSession,
  type PermissionAction,
  type PermissionChecker,
  type PermissionObject,
  type PermissionRequirement
} from '@/lib/rbac';
import { useAuthContext } from './auth-provider';

export type PermissionContextValue = {
  ready: boolean;
  checker: PermissionChecker;
  can: (object: PermissionObject, action: PermissionAction) => boolean;
  canAny: (requirements: readonly PermissionRequirement[]) => boolean;
  canAll: (requirements: readonly PermissionRequirement[]) => boolean;
};

const denyAllChecker: PermissionChecker = {
  can: () => false,
  canAny: () => false,
  canAll: () => false
};

const PermissionContext = React.createContext<PermissionContextValue>({
  ready: false,
  checker: denyAllChecker,
  can: () => false,
  canAny: () => false,
  canAll: () => false
});

function sessionToIdentity(user: SessionUser | null) {
  if (!user) {
    return identityFromSession({ role: 'operator', orgRole: 'member' });
  }
  return identityFromSession({
    role: user.role,
    orgRole: user.orgRole
  });
}

export function PermissionProvider({ children }: { children: React.ReactNode }) {
  const { pending, user } = useAuthContext();

  const value = React.useMemo<PermissionContextValue>(() => {
    const checker = createPermissionChecker(sessionToIdentity(user));
    return {
      ready: !pending,
      checker,
      can: checker.can.bind(checker),
      canAny: checker.canAny.bind(checker),
      canAll: checker.canAll.bind(checker)
    };
  }, [pending, user]);

  return (
    <PermissionContext.Provider value={value}>
      {children}
    </PermissionContext.Provider>
  );
}

export function usePermissionContext() {
  return React.useContext(PermissionContext);
}
