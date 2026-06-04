import { describe, expect, it } from 'vitest';
import { pickDefaultOrganization } from './pick-default-organization';
import type { ProtoOrganization } from '@/features/device-farm';

function org(
  id: string,
  businessName: string,
  businessEmail?: string
): ProtoOrganization {
  return {
    id,
    businessName,
    businessEmail: businessEmail ?? null,
    businessLogo: null
  };
}

describe('pickDefaultOrganization', () => {
  it('prefers defaultOrgId over stored personal workspace', () => {
    const orgs = [
      org('team', "Hoang Le's Workspace", 'dev@gmail.com'),
      org('mine', "Hoang Le's Workspace", 'guest@gmail.com')
    ];
    const picked = pickDefaultOrganization(orgs, 'mine', {
      preferredOrgId: 'team',
      userEmail: 'guest@gmail.com'
    });
    expect(picked.id).toBe('team');
  });

  it('prefers collaboration org when no defaultOrgId', () => {
    const orgs = [
      org('team', "Hoang Le's Workspace", 'dev@gmail.com'),
      org('mine', "Hoang Le's Workspace", 'guest@gmail.com')
    ];
    const picked = pickDefaultOrganization(orgs, 'mine', {
      userEmail: 'guest@gmail.com'
    });
    expect(picked.id).toBe('team');
  });
});
