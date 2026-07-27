import { createScrcpyViewerId } from './scrcpy-stream';

export type ScrcpyViewerRole =
  | 'campaign-monitor'
  | 'control-screen'
  | 'follower-preview';

type ViewerIdFactory = (role: string) => string;

export function createScrcpyViewerSession(
  role: ScrcpyViewerRole,
  createId: ViewerIdFactory = createScrcpyViewerId
) {
  const viewerIds = new Map<string, string>();

  return {
    idFor(serial: string): string {
      const existing = viewerIds.get(serial);
      if (existing) return existing;
      const viewerId = createId(role);
      viewerIds.set(serial, viewerId);
      return viewerId;
    }
  };
}
