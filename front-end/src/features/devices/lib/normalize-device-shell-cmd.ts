/**
 * Accept bare device shell (`getprop foo`) or a full adb shell line
 * (`adb shell …`, `adb -s SERIAL shell …`). Returns the shell payload for relay.
 */
export function normalizeDeviceShellCommand(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return trimmed;

  const adbShell = trimmed.match(/^adb(?:\s+-s\s+\S+)?\s+shell\s+(.*)$/is);
  if (adbShell) {
    return adbShell[1]?.trim() ?? '';
  }

  if (/^adb(?:\s+-s\s+\S+)?\s+shell\s*$/i.test(trimmed)) {
    return '';
  }

  return trimmed;
}
