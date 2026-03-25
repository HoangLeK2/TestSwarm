'use client';

import React from 'react';
import type { ProtoOrganization } from '@/features/device-farm';
import { listOrganizations } from '../services/farm-org-api';

type OrganizationContextValue = {
  organizations: ProtoOrganization[];
  currentOrg: ProtoOrganization | null;
  setCurrentOrg: (org: ProtoOrganization | null) => void;
};

const OrganizationContext = React.createContext<OrganizationContextValue | null>(
  null
);

export function OrganizationProvider({ children }: { children: React.ReactNode }) {
  const [organizations, setOrganizations] = React.useState<ProtoOrganization[]>([]);
  const [currentOrg, setCurrentOrg] = React.useState<ProtoOrganization | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    listOrganizations()
      .then((orgs) => {
        if (cancelled) return;
        setOrganizations(orgs);
        if (!currentOrg && orgs.length > 0) {
          setCurrentOrg(orgs[0]);
        }
      })
      .catch(() => {
        if (cancelled) return;
        setOrganizations([]);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const value = React.useMemo<OrganizationContextValue>(
    () => ({
      organizations,
      currentOrg,
      setCurrentOrg
    }),
    [organizations, currentOrg]
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
      setCurrentOrg: () => {}
    } satisfies OrganizationContextValue;
  }
  return ctx;
}

