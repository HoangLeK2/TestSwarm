type HardwareFailureStorage = {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
};

type StorageAccessor = () => HardwareFailureStorage | null;

const STORAGE_KEY_PREFIX = 'devicefarm_h264_hardware_failed:';

function browserSessionStorage(): HardwareFailureStorage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function createH264HardwareFailureRegistry(
  storageAccessor: StorageAccessor = browserSessionStorage
) {
  const failedSerials = new Set<string>();

  return {
    has(serial: string): boolean {
      if (!serial) return false;
      if (failedSerials.has(serial)) return true;
      try {
        if (
          storageAccessor()?.getItem(`${STORAGE_KEY_PREFIX}${serial}`) === '1'
        ) {
          failedSerials.add(serial);
          return true;
        }
      } catch {
        // In-memory state remains available when session storage is blocked.
      }
      return false;
    },

    remember(serial: string): void {
      if (!serial) return;
      failedSerials.add(serial);
      try {
        storageAccessor()?.setItem(`${STORAGE_KEY_PREFIX}${serial}`, '1');
      } catch {
        // In-memory state is enough for the current mount.
      }
    }
  };
}

export const h264HardwareFailureRegistry = createH264HardwareFailureRegistry();
