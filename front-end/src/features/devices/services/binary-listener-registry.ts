export type BinaryListener = {
  fn: (buf: ArrayBuffer) => void;
  serial?: string;
};

export class BinaryListenerRegistry {
  private readonly listeners = new Set<BinaryListener>();
  private readonly unscopedListeners = new Set<BinaryListener>();
  private readonly listenersBySerial = new Map<string, Set<BinaryListener>>();

  get size(): number {
    return this.listeners.size;
  }

  add(listener: BinaryListener): void {
    if (this.listeners.has(listener)) return;
    this.listeners.add(listener);

    if (!listener.serial) {
      this.unscopedListeners.add(listener);
      return;
    }

    let scoped = this.listenersBySerial.get(listener.serial);
    if (!scoped) {
      scoped = new Set<BinaryListener>();
      this.listenersBySerial.set(listener.serial, scoped);
    }
    scoped.add(listener);
  }

  delete(listener: BinaryListener): boolean {
    if (!this.listeners.delete(listener)) return false;

    if (!listener.serial) {
      this.unscopedListeners.delete(listener);
      return true;
    }

    const scoped = this.listenersBySerial.get(listener.serial);
    scoped?.delete(listener);
    if (scoped?.size === 0) {
      this.listenersBySerial.delete(listener.serial);
    }
    return true;
  }

  dispatch(buf: ArrayBuffer, serial: string | null): void {
    if (serial === null) {
      this.notify(this.listeners, buf);
      return;
    }

    this.notify(this.unscopedListeners, buf);
    const scoped = this.listenersBySerial.get(serial);
    if (scoped) this.notify(scoped, buf);
  }

  private notify(listeners: Set<BinaryListener>, buf: ArrayBuffer): void {
    listeners.forEach(({ fn }) => {
      try {
        fn(buf);
      } catch {
        // One decoder must not block other subscribers for the same frame.
      }
    });
  }
}
