import {
  attachScrcpyStream,
  createScrcpyViewerId,
  detachScrcpyStream,
  type ScrcpyAttachOptions
} from './scrcpy-stream';

const SNAPSHOT_WARMUP_LIMIT = (() => {
  const raw = Number(
    process.env.NEXT_PUBLIC_DEVICE_FARM_SNAPSHOT_WARMUP_LIMIT ?? 3
  );
  if (!Number.isFinite(raw)) return 3;
  return Math.max(1, Math.min(64, Math.round(raw)));
})();

const SNAPSHOT_WARMUP_RELEASE_GRACE_MS = (() => {
  const raw = Number(
    process.env.NEXT_PUBLIC_DEVICE_FARM_SNAPSHOT_WARMUP_RELEASE_GRACE_MS ?? 700
  );
  if (!Number.isFinite(raw)) return 700;
  return Math.max(0, Math.min(10_000, Math.round(raw)));
})();

const PREVIEW_SCRCPY_OPTIONS: ScrcpyAttachOptions = {
  enableControl: true,
  maxFps: (() => {
    const raw = Number(
      process.env.NEXT_PUBLIC_DEVICE_FARM_PREVIEW_SCRCPY_FPS ?? 1
    );
    if (!Number.isFinite(raw)) return 1;
    return Math.max(1, Math.min(8, Math.round(raw)));
  })(),
  maxWidth: (() => {
    const raw = Number(
      process.env.NEXT_PUBLIC_DEVICE_FARM_PREVIEW_SCRCPY_WIDTH ?? 360
    );
    if (!Number.isFinite(raw)) return 360;
    return Math.max(240, Math.min(540, Math.round(raw)));
  })(),
  bitrate: (() => {
    const raw = Number(
      process.env.NEXT_PUBLIC_DEVICE_FARM_PREVIEW_SCRCPY_BITRATE ?? 100_000
    );
    if (!Number.isFinite(raw)) return 100_000;
    return Math.max(80_000, Math.min(600_000, Math.round(raw)));
  })()
};

type WarmupEntry = {
  viewerId: string;
  refs: number;
  attached: Promise<boolean>;
  settled: boolean;
  releaseTimer: ReturnType<typeof setTimeout> | null;
};

export type SnapshotPreviewWarmupHandle = {
  attached: Promise<boolean>;
  release: () => void;
};

const activeWarmups = new Map<string, WarmupEntry>();
const warmupListeners = new Set<() => void>();

function detachWarmupEntry(serial: string, entry: WarmupEntry) {
  void entry.attached.finally(() => {
    detachScrcpyStream(serial, entry.viewerId).catch(() => {});
  });
}

function finalizeUnusedWarmup(serial: string, entry: WarmupEntry) {
  const current = activeWarmups.get(serial);
  if (!current || current.viewerId !== entry.viewerId || current.refs > 0)
    return;
  if (!current.settled) {
    current.releaseTimer = null;
    void current.attached.finally(() => finalizeUnusedWarmup(serial, current));
    return;
  }
  activeWarmups.delete(serial);
  emitWarmupChange();
  detachWarmupEntry(serial, current);
}

function evictUnusedRetainedWarmup(): boolean {
  const retained = Array.from(activeWarmups.entries()).find(
    ([, entry]) => entry.refs <= 0 && entry.settled
  );
  if (!retained) return false;
  const [serial, entry] = retained;
  if (entry.releaseTimer) clearTimeout(entry.releaseTimer);
  entry.releaseTimer = null;
  activeWarmups.delete(serial);
  emitWarmupChange();
  detachWarmupEntry(serial, entry);
  return true;
}

function emitWarmupChange() {
  queueMicrotask(() => {
    warmupListeners.forEach((listener) => {
      try {
        listener();
      } catch {
        // isolate subscribers
      }
    });
  });
}

export function subscribeSnapshotPreviewWarmupChanges(
  listener: () => void
): () => void {
  warmupListeners.add(listener);
  return () => {
    warmupListeners.delete(listener);
  };
}

export function getSnapshotPreviewWarmupLimit(): number {
  return SNAPSHOT_WARMUP_LIMIT;
}

export function getSnapshotPreviewWarmupActiveCount(): number {
  return activeWarmups.size;
}

export function acquireSnapshotPreviewWarmup(
  serial: string
): SnapshotPreviewWarmupHandle | null {
  if (!serial) return null;

  let entry = activeWarmups.get(serial);
  if (!entry) {
    if (
      activeWarmups.size >= SNAPSHOT_WARMUP_LIMIT &&
      !evictUnusedRetainedWarmup()
    )
      return null;
    const viewerId = createScrcpyViewerId('snapshot-preview');
    const newEntry: WarmupEntry = {
      viewerId,
      refs: 0,
      settled: false,
      releaseTimer: null,
      attached: Promise.resolve(false)
    };
    newEntry.attached = attachScrcpyStream(
      serial,
      viewerId,
      PREVIEW_SCRCPY_OPTIONS
    )
      .then(() => true)
      .catch(() => {
        const current = activeWarmups.get(serial);
        if (current?.viewerId === viewerId) {
          activeWarmups.delete(serial);
          emitWarmupChange();
        }
        return false;
      })
      .finally(() => {
        newEntry.settled = true;
      });
    entry = newEntry;
    activeWarmups.set(serial, entry);
    emitWarmupChange();
  }

  if (entry.releaseTimer) {
    clearTimeout(entry.releaseTimer);
    entry.releaseTimer = null;
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
      current.releaseTimer = setTimeout(() => {
        const retained = activeWarmups.get(serial);
        if (!retained || retained.viewerId !== current.viewerId) return;
        retained.releaseTimer = null;
        if (retained.refs > 0) return;
        finalizeUnusedWarmup(serial, retained);
      }, SNAPSHOT_WARMUP_RELEASE_GRACE_MS);
    }
  };
}
