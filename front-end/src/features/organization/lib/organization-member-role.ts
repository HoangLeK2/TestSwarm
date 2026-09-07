export type OrganizationMemberRoleLabelKey =
  | 'owner'
  | 'admin'
  | 'staff'
  | 'supervisor';

export function organizationMemberRoleLabelKey(
  role: string
): OrganizationMemberRoleLabelKey {
  if (role === 'owner') return 'owner';
  if (role === 'admin') return 'admin';
  if (role === 'supervisor') return 'supervisor';
  return 'staff';
}

export function isEditableOrganizationMemberRole(role: string): boolean {
  return role === 'member' || role === 'supervisor';
}
