type Listener = (serial: string | null) => void;

let activeSerial: string | null = null;
const listeners = new Set<Listener>();

function emit(serial: string | null) {
  listeners.forEach((listener) => {
    try {
      listener(serial);
    } catch {
      // isolate subscribers
    }
  });
}

export function getCampaignMonitorLiveMirrorSerial(): string | null {
  return activeSerial;
}

export function subscribeCampaignMonitorLiveMirror(
  listener: Listener
): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** At most one campaign-monitor live scrcpy mirror at a time. */
export function claimCampaignMonitorLiveMirror(serial: string): void {
  const next = (serial ?? '').trim() || null;
  if (!next || activeSerial === next) return;
  activeSerial = next;
  emit(activeSerial);
}

export function releaseCampaignMonitorLiveMirror(serial: string): void {
  const current = (serial ?? '').trim();
  if (!current || activeSerial !== current) return;
  activeSerial = null;
  emit(null);
}
