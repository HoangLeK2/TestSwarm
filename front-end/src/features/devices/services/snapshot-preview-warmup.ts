import {
  attachScrcpyStream,
  createScrcpyViewerId,
  detachScrcpyStream
} from './scrcpy-stream';

const SNAPSHOT_WARMUP_LIMIT = (() => {
  const raw = Number(
    process.env.NEXT_PUBLIC_DEVICE_FARM_SNAPSHOT_WARMUP_LIMIT ?? 4
  );
  if (!Number.isFinite(raw)) return 4;
  return Math.max(1, Math.min(12, Math.round(raw)));
})();

type WarmupEntry = {
  viewerId: string;
  refs: number;
  attached: Promise<boolean>;
};

export type SnapshotPreviewWarmupHandle = {
  attached: Promise<boolean>;
  release: () => void;
};

const activeWarmups = new Map<string, WarmupEntry>();

export function acquireSnapshotPreviewWarmup(
  serial: string
): SnapshotPreviewWarmupHandle | null {
  if (!serial) return null;

  let entry = activeWarmups.get(serial);
  if (!entry) {
    if (activeWarmups.size >= SNAPSHOT_WARMUP_LIMIT) return null;
    const viewerId = createScrcpyViewerId('snapshot-preview');
    entry = {
      viewerId,
      refs: 0,
      attached: attachScrcpyStream(serial, viewerId)
        .then(() => true)
        .catch(() => {
          const current = activeWarmups.get(serial);
          if (current?.viewerId === viewerId) {
            activeWarmups.delete(serial);
          }
          return false;
        })
    };
    activeWarmups.set(serial, entry);
  }

  entry.refs += 1;
  let released = false;

  return {
    attached: entry.attached,
    release: () => {
      if (released) return;
      released = true;
      const current = activeWarmups.get(serial);
      if (!current || current.viewerId !== entry.viewerId) return;
      current.refs -= 1;
      if (current.refs > 0) return;
      activeWarmups.delete(serial);
      detachScrcpyStream(serial, current.viewerId).catch(() => {});
    }
  };
}
