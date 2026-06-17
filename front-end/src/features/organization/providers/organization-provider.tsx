'use client';

import React from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { ProtoOrganization } from '@/features/device-farm';
import { useAuthContext } from '@/features/auth/providers/auth-provider';
import {
  DEVICES_LIST_KEY,
  FLEET_STATS_KEY
} from '@/features/devices/lib/device-query-keys';
import { pickDefaultOrganization } from '../lib/pick-default-organization';
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
  const { user } = useAuthContext();
  const {
    data: organizations = [],
    isLoading,
    isError,
    refetch
  } = useOrganizationsQuery();
  const [currentOrg, setCurrentOrgState] =
    React.useState<ProtoOrganization | null>(null);

  React.useEffect(() => {
    if (!organizations.length) {
      setCurrentOrgState(null);
      return;
    }

    setCurrentOrgState((prev) => {
      const storedId =
        typeof window !== 'undefined'
          ? localStorage.getItem(CURRENT_ORG_STORAGE_KEY)?.trim() || null
          : null;

      const picked = pickDefaultOrganization(organizations, storedId, {
        preferredOrgId: user?.defaultOrgId,
        userEmail: user?.email
      });

      const preferred = (user?.defaultOrgId ?? '').trim();
      if (preferred) {
        const preferredOrg = organizations.find((o) => o.id === preferred);
        if (preferredOrg && prev?.id !== preferred) return preferredOrg;
      }

      if (prev && organizations.some((o) => o.id === prev.id)) {
        return organizations.find((o) => o.id === prev.id) ?? prev;
      }

      return picked;
    });
  }, [organizations, user?.defaultOrgId, user?.email]);

  const setCurrentOrg = React.useCallback((org: ProtoOrganization | null) => {
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
