type SlotListener = () => void;
type SlotRelease = () => void;

export type FollowerH264SlotPool = {
  acquire: () => SlotRelease | null;
  subscribe: (listener: SlotListener) => () => void;
  getActiveCount: () => number;
};

export function createFollowerH264SlotPool(
  requestedLimit: number
): FollowerH264SlotPool {
  const limit = Math.max(1, Math.floor(requestedLimit));
  const listeners = new Set<SlotListener>();
  let activeCount = 0;

  return {
    acquire() {
      if (activeCount >= limit) return null;
      activeCount += 1;
      let released = false;
      return () => {
        if (released) return;
        released = true;
        activeCount = Math.max(0, activeCount - 1);
        listeners.forEach((listener) => listener());
      };
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getActiveCount() {
      return activeCount;
    }
  };
}

const configuredLimit = Number(
  process.env.NEXT_PUBLIC_DEVICE_FARM_FOLLOWER_H264_LIMIT ?? 4
);
const followerH264SlotPool = createFollowerH264SlotPool(
  Number.isFinite(configuredLimit)
    ? Math.max(1, Math.min(20, configuredLimit))
    : 4
);

export const acquireFollowerH264Slot = followerH264SlotPool.acquire;
export const subscribeFollowerH264SlotChanges = followerH264SlotPool.subscribe;
export const getFollowerH264ActiveCount = followerH264SlotPool.getActiveCount;
