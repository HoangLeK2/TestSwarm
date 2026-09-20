/**
 * Device targeting for a schedule: all ready devices, a device group, or an
 * explicit list of serials. Pure logic so it can be tested without React.
 */

export type ScheduleDeviceMode = 'all' | 'group' | 'devices';

export function resolveScheduleDeviceMode(
  schedule:
    | {
        device_group_id?: string | null;
        device_serials?: string[] | null;
      }
    | null
    | undefined
): ScheduleDeviceMode {
  if (schedule?.device_serials?.length) return 'devices';
  if (schedule?.device_group_id) return 'group';
  return 'all';
}

/**
 * Payload fragment for create *and* patch. `null` / `[]` are meaningful: they
 * clear the other mode's targeting, so never replace them with `undefined`.
 */
export function buildScheduleDeviceTarget(
  mode: ScheduleDeviceMode,
  groupId: string | null,
  serials: string[]
): { device_group_id: string | null; device_serials: string[] } {
  if (mode === 'group') {
    return { device_group_id: groupId, device_serials: [] };
  }
  if (mode === 'devices') {
    return { device_group_id: null, device_serials: serials };
  }
  return { device_group_id: null, device_serials: [] };
}
