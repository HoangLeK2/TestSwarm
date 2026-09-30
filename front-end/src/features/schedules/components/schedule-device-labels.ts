export type ScheduleDeviceLabelSource = {
  serial: string;
  name?: string | null;
};

/** Resolve selected schedule serials to the best friendly names currently known. */
export function resolveScheduleDeviceLabels(
  selectedSerials: readonly string[],
  currentPage: readonly ScheduleDeviceLabelSource[],
  allDevices: readonly ScheduleDeviceLabelSource[]
): Map<string, string> {
  const knownLabels = new Map<string, string>();

  for (const device of [...allDevices, ...currentPage]) {
    const friendlyName = device.name?.trim();
    if (friendlyName || !knownLabels.has(device.serial)) {
      knownLabels.set(device.serial, friendlyName || device.serial);
    }
  }

  return new Map(
    selectedSerials.map((serial) => [serial, knownLabels.get(serial) ?? serial])
  );
}
