import assert from 'node:assert/strict';
import test from 'node:test';

import { connectLifecycleWs } from './lifecycle-ws';

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  closeCalls = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close() {
    this.closeCalls += 1;
    this.readyState = FakeWebSocket.CLOSED;
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }
}

function installBrowserGlobals() {
  const descriptors = new Map<PropertyKey, PropertyDescriptor | undefined>();
  const timers = new Map<number, () => void>();
  let nextTimerId = 1;
  const setGlobal = (key: PropertyKey, value: unknown) => {
    descriptors.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, {
      configurable: true,
      writable: true,
      value
    });
  };

  setGlobal('window', {});
  setGlobal('location', { protocol: 'http:', hostname: 'device-farm.test' });
  setGlobal('localStorage', {
    getItem: (key: string) => (key === 'auth_token' ? 'test-token' : null)
  });
  setGlobal('WebSocket', FakeWebSocket);
  setGlobal('setTimeout', (callback: () => void) => {
    const timerId = nextTimerId;
    nextTimerId += 1;
    timers.set(timerId, callback);
    return timerId;
  });
  setGlobal('clearTimeout', (timerId: number) => {
    timers.delete(Number(timerId));
  });

  return {
    runTimers() {
      const callbacks: Array<() => void> = [];
      timers.forEach((callback) => callbacks.push(callback));
      timers.clear();
      callbacks.forEach((callback) => callback());
    },
    restore() {
      descriptors.forEach((descriptor, key) => {
        if (descriptor) {
          Object.defineProperty(globalThis, key, descriptor);
        } else {
          Reflect.deleteProperty(globalThis, key);
        }
      });
      FakeWebSocket.instances = [];
    }
  };
}

test('cleanup waits for a connecting lifecycle socket to open before closing it', () => {
  const browser = installBrowserGlobals();
  const connectionChanges: boolean[] = [];

  try {
    const handle = connectLifecycleWs(
      () => {},
      (connected) => connectionChanges.push(connected)
    );
    const socket = FakeWebSocket.instances[0];
    assert.ok(socket);

    handle.close();

    assert.equal(socket.closeCalls, 0);
    assert.deepEqual(connectionChanges, [false]);

    socket.open();

    assert.equal(socket.closeCalls, 1);
    assert.deepEqual(connectionChanges, [false]);
  } finally {
    browser.restore();
  }
});

test('cleanup force-closes a lifecycle socket when its handshake stalls', () => {
  const browser = installBrowserGlobals();

  try {
    const handle = connectLifecycleWs(() => {});
    const socket = FakeWebSocket.instances[0];
    assert.ok(socket);

    handle.close();
    assert.equal(socket.closeCalls, 0);

    browser.runTimers();

    assert.equal(socket.closeCalls, 1);
    assert.equal(socket.readyState, FakeWebSocket.CLOSED);
  } finally {
    browser.restore();
  }
});
