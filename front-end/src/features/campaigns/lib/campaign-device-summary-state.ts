export function shouldFetchExplicitCampaignDevices(
  initialDevices: readonly unknown[] | undefined,
  popoverOpen: boolean,
  addDialogOpen: boolean
) {
  return popoverOpen || addDialogOpen || initialDevices === undefined;
}

export function resolveExplicitCampaignDevices<T>(
  fetchedDevices: T[] | undefined,
  initialDevices: T[] | undefined
) {
  return fetchedDevices ?? initialDevices ?? [];
}

export function explicitCampaignDeviceAssignmentsKnown(
  fetchedDevices: readonly unknown[] | undefined,
  initialDevices: readonly unknown[] | undefined
) {
  return fetchedDevices !== undefined || Array.isArray(initialDevices);
}
