'use client';

import { useOrganizationContext } from '../providers/organization-provider';

export function useOrganization() {
  return useOrganizationContext();
}
