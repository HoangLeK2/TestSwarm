'use client';

import React from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { ProtoOrganization } from '@/features/device-farm';
import { useAuthContext } from '@/features/auth/providers/auth-provider';
import { authApi } from '@/features/auth/services/api';
import {
  DEVICES_LIST_KEY,
  FLEET_STATS_KEY
} from '@/features/devices/lib/device-query-keys';
import { tokenStorage } from '@/lib/token-storage';
import { createPendingOrganizationShell } from '../lib/organization-shell';
import { reconcileCurrentOrganization } from '../lib/pick-default-organization';
import { useOrganizationsQuery } from '../hooks/use-organizations';

const CURRENT_ORG_STORAGE_KEY = 'device-farm:current-organization-id';

type OrganizationContextValue = {
  organizations: ProtoOrganization[];
  currentOrg: ProtoOrganization | null;
  setCurrentOrg: (org: ProtoOrganization | null) => void;
  isLoading: boolean;
  isError: boolean;
  refetch: () => void;
};

const OrganizationContext =
  React.createContext<OrganizationContextValue | null>(null);

export function OrganizationProvider({
  children
}: {
  children: React.ReactNode;
}) {
  const queryClient = useQueryClient();
  const { pending: authPending, user, setUser } = useAuthContext();
  const getStoredOrgId = React.useCallback(() => {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(CURRENT_ORG_STORAGE_KEY)?.trim() || null;
  }, []);
  const bootstrapOrgId = getStoredOrgId() || user?.defaultOrgId || null;
  const {
    data: organizationData,
    isFetching,
    isLoading,
    isPending,
    isError,
    refetch
  } = useOrganizationsQuery({
    enabled: !authPending && Boolean(user),
    ensureId: bootstrapOrgId
  });
  const organizations = React.useMemo(
    () => organizationData ?? [],
    [organizationData]
  );
  const [currentOrg, setCurrentOrgState] =
    React.useState<ProtoOrganization | null>(null);

  React.useEffect(() => {
    if (authPending) return;

    if (!user) {
      setCurrentOrgState(null);
      return;
    }

    const queryInFlightOrUnreliable =
      !organizationData || isLoading || isPending || isFetching || isError;

    if (!organizations.length) {
      if (queryInFlightOrUnreliable) {
        setCurrentOrgState((prev) => {
          if (prev?.id) return prev;
          return createPendingOrganizationShell({
            defaultOrgId: user.defaultOrgId,
            storedOrgId: getStoredOrgId(),
            userEmail: user.email
          });
        });
        return;
      }
      setCurrentOrgState(null);
      return;
    }

    setCurrentOrgState((prev) => {
      const storedId = getStoredOrgId();

      return reconcileCurrentOrganization(organizations, prev, storedId, {
        preferredOrgId: storedId || user?.defaultOrgId,
        userEmail: user?.email
      });
    });
  }, [
    authPending,
    isError,
    isFetching,
    isLoading,
    isPending,
    organizationData,
    organizations,
    getStoredOrgId,
    bootstrapOrgId,
    user,
    user?.defaultOrgId,
    user?.email
  ]);

  const setCurrentOrg = React.useCallback((org: ProtoOrganization | null) => {
    if (typeof window !== 'undefined') {
      if (org?.id) {
        localStorage.setItem(CURRENT_ORG_STORAGE_KEY, org.id);
      } else {
        localStorage.removeItem(CURRENT_ORG_STORAGE_KEY);
      }
    }
    setCurrentOrgState(org);
  }, []);

  // Keep X-Organization-Id (farmApi interceptor) aligned with UI org selection.
  React.useEffect(() => {
    if (typeof window === 'undefined') return;
    if (currentOrg?.id) {
      localStorage.setItem(CURRENT_ORG_STORAGE_KEY, currentOrg.id);
    } else {
      localStorage.removeItem(CURRENT_ORG_STORAGE_KEY);
    }
  }, [currentOrg?.id]);

  React.useEffect(() => {
    if (authPending || !user || !currentOrg?.id) return;

    let cancelled = false;
    const currentUser = user;

    async function refreshSessionForCurrentOrg() {
      try {
        const me = await authApi.me();
        if (cancelled) return;

        const nextUser = {
          id: me.id,
          email: me.email,
          givenName: me.name,
          picture: currentUser.picture ?? null,
          role: me.role,
          orgRole: me.orgRole ?? null,
          defaultOrgId: me.defaultOrgId ?? null,
          mustChangePassword: Boolean(me.mustChangePassword)
        };
        const unchanged =
          nextUser.id === currentUser.id &&
          nextUser.email === currentUser.email &&
          nextUser.givenName === currentUser.givenName &&
          nextUser.picture === (currentUser.picture ?? null) &&
          nextUser.role === currentUser.role &&
          nextUser.orgRole === currentUser.orgRole &&
          nextUser.defaultOrgId === currentUser.defaultOrgId &&
          nextUser.mustChangePassword === currentUser.mustChangePassword;
        if (unchanged) return;

        tokenStorage.setUser(nextUser);
        setUser(nextUser);
      } catch {
        // Keep the existing auth snapshot; route requests still carry the active org header.
      }
    }

    void refreshSessionForCurrentOrg();
    return () => {
      cancelled = true;
    };
  }, [
    authPending,
    currentOrg?.id,
    setUser,
    user,
    user?.defaultOrgId,
    user?.email,
    user?.givenName,
    user?.id,
    user?.mustChangePassword,
    user?.orgRole,
    user?.picture,
    user?.role
  ]);

  React.useEffect(() => {
    if (!currentOrg?.id) return;
    void queryClient.invalidateQueries({ queryKey: DEVICES_LIST_KEY });
    void queryClient.invalidateQueries({ queryKey: FLEET_STATS_KEY });
    void queryClient.invalidateQueries({ queryKey: ['accounts'] });
    void queryClient.invalidateQueries({ queryKey: ['account-groups'] });
    void queryClient.invalidateQueries({ queryKey: ['notifications'] });
    void queryClient.invalidateQueries({
      queryKey: ['control-record-device-map']
    });
    void queryClient.invalidateQueries({ queryKey: ['relay-agents'] });
  }, [currentOrg?.id, queryClient]);

  const value = React.useMemo<OrganizationContextValue>(
    () => ({
      organizations,
      currentOrg,
      setCurrentOrg,
      isLoading,
      isError,
      refetch: () => {
        void refetch();
      }
    }),
    [organizations, currentOrg, setCurrentOrg, isLoading, isError, refetch]
  );

  return (
    <OrganizationContext.Provider value={value}>
      {children}
    </OrganizationContext.Provider>
  );
}

export function useOrganizationContext() {
  const ctx = React.useContext(OrganizationContext);
  if (!ctx) {
    return {
      organizations: [],
      currentOrg: null,
      setCurrentOrg: () => {},
      isLoading: false,
      isError: false,
      refetch: () => {}
    } satisfies OrganizationContextValue;
  }
  return ctx;
}
