export type PhoneAllocationWorkspaceOption = {
  id: string;
  businessName: string;
};

export function selectedWorkspaceName(
  workspaces: PhoneAllocationWorkspaceOption[],
  workspaceId: string
): string {
  if (!workspaceId) return '';
  return (
    workspaces.find((workspace) => workspace.id === workspaceId)
      ?.businessName ?? ''
  );
}

export function canAssignPhones({
  selectedCount,
  targetWorkspaceId,
  targetWorkspaceName
}: {
  selectedCount: number;
  targetWorkspaceId: string;
  targetWorkspaceName: string;
}): boolean {
  return (
    selectedCount > 0 &&
    Boolean(targetWorkspaceId) &&
    Boolean(targetWorkspaceName)
  );
}

export function showReturnToPoolAction(selectedCount: number): boolean {
  return selectedCount > 0;
}
