'use client';

import { useEffect, useMemo, useState } from 'react';
import { useUser } from '@/features/auth';
import { useOrganization } from '@/features/organization/hooks/use-organization';

export const ADMIN_ALL_WORKSPACES = '__all__';

export function useAdminWorkspaceScope() {
  const { user } = useUser();
  const { currentOrg, organizations } = useOrganization();
  const isSuperadmin = user?.role === 'superadmin';
  const isWorkspaceAdmin = user?.orgRole === 'admin';
  const allowGlobalScope = isSuperadmin || isWorkspaceAdmin;
  const [workspaceId, setWorkspaceId] = useState(ADMIN_ALL_WORKSPACES);
  const [userSelectedScope, setUserSelectedScope] = useState(false);

  useEffect(() => {
    if (userSelectedScope) return;
    if (allowGlobalScope) {
      setWorkspaceId(ADMIN_ALL_WORKSPACES);
    } else if (currentOrg?.id) {
      setWorkspaceId(currentOrg.id);
    }
  }, [allowGlobalScope, currentOrg?.id, userSelectedScope]);

  const setScopeWorkspaceId = (value: string) => {
    setUserSelectedScope(true);
    setWorkspaceId(value);
  };

  const scopedWorkspaceId =
    workspaceId === ADMIN_ALL_WORKSPACES ? undefined : workspaceId;
  const currentWorkspaceName = useMemo(() => {
    if (workspaceId === ADMIN_ALL_WORKSPACES) return null;
    return (
      organizations.find((org) => org.id === workspaceId)?.businessName ?? null
    );
  }, [organizations, workspaceId]);

  return {
    isSuperadmin,
    workspaceId,
    scopedWorkspaceId,
    currentWorkspaceName,
    workspaces: organizations,
    setWorkspaceId: setScopeWorkspaceId,
    allowGlobalScope
  };
}
