'use client';

import React from 'react';
import type { ProtoOrganization } from '@/features/device-farm';
import { useOrganizationsQuery } from '../hooks/use-organizations';

const CURRENT_ORG_STORAGE_KEY = 'device-farm:current-organization-id';

function isPersonalWorkspaceName(name: string | undefined | null): boolean {
  return Boolean(name?.trim().endsWith("'s Workspace"));
}

function pickDefaultOrganization(
  organizations: ProtoOrganization[],
  storedId: string | null
): ProtoOrganization {
  if (storedId) {
    const fromStorage = organizations.find((o) => o.id === storedId);
    if (fromStorage) return fromStorage;
  }
  const shared = organizations.filter(
    (o) => !isPersonalWorkspaceName(o.businessName)
  );
  return shared[0] ?? organizations[0];
}

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
      if (prev && organizations.some((o) => o.id === prev.id)) {
        return organizations.find((o) => o.id === prev.id) ?? prev;
      }

      const storedId =
        typeof window !== 'undefined'
          ? localStorage.getItem(CURRENT_ORG_STORAGE_KEY)?.trim() || null
          : null;

      return pickDefaultOrganization(organizations, storedId);
    });
  }, [organizations]);

  const setCurrentOrg = React.useCallback((org: ProtoOrganization | null) => {
    setCurrentOrgState(org);
    if (typeof window === 'undefined') return;
    if (org) {
      localStorage.setItem(CURRENT_ORG_STORAGE_KEY, org.id);
    } else {
      localStorage.removeItem(CURRENT_ORG_STORAGE_KEY);
    }
  }, []);

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
