export function resolveClientOrganizationId(
  scopedOrganizationId: string | null | undefined,
  storedOrganizationId: string | null | undefined
): string | null {
  return scopedOrganizationId?.trim() || storedOrganizationId?.trim() || null;
}
