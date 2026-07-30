import {
  attachScrcpyStream,
  cancelPendingScrcpyAttach,
  createScrcpyViewerId,
  detachScrcpyStream,
  type ScrcpyAttachOptions
} from './scrcpy-stream';

const PREVIEW_ATTACH_CONCURRENCY = (() => {
  const raw = Number(
    process.env.NEXT_PUBLIC_DEVICE_FARM_PREVIEW_ATTACH_CONCURRENCY ?? 3
  );
  if (!Number.isFinite(raw)) return 3;
  return Math.max(1, Math.min(8, Math.round(raw)));
})();

const SNAPSHOT_WARMUP_RELEASE_GRACE_MS = (() => {
  const raw = Number(
    process.env.NEXT_PUBLIC_DEVICE_FARM_SNAPSHOT_WARMUP_RELEASE_GRACE_MS ??
      12_000
  );
  if (!Number.isFinite(raw)) return 12_000;
  return Math.max(0, Math.min(60_000, Math.round(raw)));
})();

const SNAPSHOT_WARMUP_RETAINED_IDLE_LIMIT = (() => {
  const raw = Number(
    process.env.NEXT_PUBLIC_DEVICE_FARM_SNAPSHOT_WARMUP_RETAINED_IDLE_LIMIT ?? 8
  );
  if (!Number.isFinite(raw)) return 8;
  return Math.max(0, Math.min(64, Math.round(raw)));
})();

const PREVIEW_SCRCPY_OPTIONS: ScrcpyAttachOptions = {
  enableControl: false,
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
  started: Promise<boolean>;
  resolveStarted: (started: boolean) => void;
  attached: Promise<boolean>;
  resolveAttached: (attached: boolean) => void;
  state: 'queued' | 'attaching' | 'settled';
  settled: boolean;
  releaseTimer: ReturnType<typeof setTimeout> | null;
  releasedAt: number;
};

export type SnapshotPreviewWarmupHandle = {
  started: Promise<boolean>;
  attached: Promise<boolean>;
  release: () => void;
};

const activeWarmups = new Map<string, WarmupEntry>();
const attachQueue: Array<{ serial: string; entry: WarmupEntry }> = [];
let attachQueueHead = 0;
let attachingWarmups = 0;

function detachWarmupEntry(serial: string, entry: WarmupEntry) {
  void entry.attached.finally(() => {
    detachScrcpyStream(serial, entry.viewerId).catch(() => {});
  });
}

function evictWarmupEntry(serial: string, entry: WarmupEntry) {
  if (entry.releaseTimer) {
    clearTimeout(entry.releaseTimer);
    entry.releaseTimer = null;
  }
  finalizeUnusedWarmup(serial, entry);
}

function trimRetainedIdleWarmups() {
  if (SNAPSHOT_WARMUP_RETAINED_IDLE_LIMIT <= 0) {
    for (const [serial, entry] of activeWarmups) {
      if (entry.refs <= 0 && entry.state === 'settled') {
        evictWarmupEntry(serial, entry);
      }
    }
    return;
  }

  const retained = Array.from(activeWarmups.entries())
    .filter(([, entry]) => entry.refs <= 0 && entry.state === 'settled')
    .sort(([, a], [, b]) => a.releasedAt - b.releasedAt);
  const overflow = retained.length - SNAPSHOT_WARMUP_RETAINED_IDLE_LIMIT;
  if (overflow <= 0) return;
  for (const [serial, entry] of retained.slice(0, overflow)) {
    evictWarmupEntry(serial, entry);
  }
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
  detachWarmupEntry(serial, current);
}

function finishWarmupAttach(
  serial: string,
  entry: WarmupEntry,
  attached: boolean
) {
  entry.state = 'settled';
  entry.settled = true;
  attachingWarmups = Math.max(0, attachingWarmups - 1);

  const current = activeWarmups.get(serial);
  if (!attached && current?.viewerId === entry.viewerId) {
    activeWarmups.delete(serial);
  }
  entry.resolveAttached(attached);

  if (attached && current?.viewerId === entry.viewerId && entry.refs <= 0) {
    finalizeUnusedWarmup(serial, entry);
  }

  pumpWarmupQueue();
}

function startWarmupAttach(serial: string, entry: WarmupEntry) {
  entry.state = 'attaching';
  attachingWarmups += 1;
  entry.resolveStarted(true);
  void attachScrcpyStream(serial, entry.viewerId, PREVIEW_SCRCPY_OPTIONS).then(
    () => finishWarmupAttach(serial, entry, true),
    () => finishWarmupAttach(serial, entry, false)
  );
}

function dequeueWarmup() {
  const queued = attachQueue[attachQueueHead];
  attachQueueHead += 1;
  if (attachQueueHead >= attachQueue.length) {
    attachQueue.length = 0;
    attachQueueHead = 0;
  } else if (
    attachQueueHead >= 64 &&
    attachQueueHead * 2 >= attachQueue.length
  ) {
    attachQueue.splice(0, attachQueueHead);
    attachQueueHead = 0;
  }
  return queued;
}

function pumpWarmupQueue() {
  while (
    attachingWarmups < PREVIEW_ATTACH_CONCURRENCY &&
    attachQueueHead < attachQueue.length
  ) {
    const queued = dequeueWarmup();
    if (!queued) continue;
    const { serial, entry } = queued;
    if (activeWarmups.get(serial) !== entry || entry.state !== 'queued')
      continue;
    if (entry.refs <= 0) {
      activeWarmups.delete(serial);
      entry.state = 'settled';
      entry.settled = true;
      entry.resolveStarted(false);
      entry.resolveAttached(false);
      continue;
    }
    startWarmupAttach(serial, entry);
  }
}

export function getSnapshotPreviewAttachConcurrency(): number {
  return PREVIEW_ATTACH_CONCURRENCY;
}

/** @deprecated Use getSnapshotPreviewAttachConcurrency(). */
export function getSnapshotPreviewWarmupLimit(): number {
  return getSnapshotPreviewAttachConcurrency();
}

export function getSnapshotPreviewWarmupActiveCount(): number {
  return activeWarmups.size;
}

export function getSnapshotPreviewAttachingCount(): number {
  return attachingWarmups;
}

export function getSnapshotPreviewRetainedIdleLimit(): number {
  return SNAPSHOT_WARMUP_RETAINED_IDLE_LIMIT;
}

export function acquireSnapshotPreviewWarmup(
  serial: string
): SnapshotPreviewWarmupHandle | null {
  if (!serial) return null;

  let entry = activeWarmups.get(serial);
  if (!entry) {
    const viewerId = createScrcpyViewerId('snapshot-preview');
    let resolveStarted!: (started: boolean) => void;
    const started = new Promise<boolean>((resolve) => {
      resolveStarted = resolve;
    });
    let resolveAttached!: (attached: boolean) => void;
    const attached = new Promise<boolean>((resolve) => {
      resolveAttached = resolve;
    });
    const newEntry: WarmupEntry = {
      viewerId,
      refs: 0,
      started,
      resolveStarted,
      attached,
      resolveAttached,
      state: 'queued',
      settled: false,
      releaseTimer: null,
      releasedAt: 0
    };
    entry = newEntry;
    activeWarmups.set(serial, entry);
    attachQueue.push({ serial, entry });
  }

  if (entry.releaseTimer) {
    clearTimeout(entry.releaseTimer);
    entry.releaseTimer = null;
  }
  entry.releasedAt = 0;
  entry.refs += 1;
  let released = false;

  const handle: SnapshotPreviewWarmupHandle = {
    started: entry.started,
    attached: entry.attached,
    release: () => {
      if (released) return;
      released = true;
      const current = activeWarmups.get(serial);
      if (!current || current.viewerId !== entry.viewerId) return;
      current.refs -= 1;
      if (current.refs > 0) return;
      if (current.state === 'queued') {
        activeWarmups.delete(serial);
        current.state = 'settled';
        current.settled = true;
        current.resolveStarted(false);
        current.resolveAttached(false);
        pumpWarmupQueue();
        return;
      }
      if (current.state === 'attaching') {
        activeWarmups.delete(serial);
        cancelPendingScrcpyAttach(serial, current.viewerId);
        detachWarmupEntry(serial, current);
        return;
      }
      current.releasedAt =
        typeof performance !== 'undefined' ? performance.now() : Date.now();
      current.releaseTimer = setTimeout(() => {
        const retained = activeWarmups.get(serial);
        if (!retained || retained.viewerId !== current.viewerId) return;
        retained.releaseTimer = null;
        if (retained.refs > 0) return;
        finalizeUnusedWarmup(serial, retained);
      }, SNAPSHOT_WARMUP_RELEASE_GRACE_MS);
      trimRetainedIdleWarmups();
    }
  };

  pumpWarmupQueue();
  return handle;
}
