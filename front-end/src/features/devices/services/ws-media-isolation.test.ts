import assert from 'node:assert/strict';
import test from 'node:test';

process.env.NEXT_PUBLIC_DEVICE_FARM_DEDICATED_MEDIA_WS = '1';
process.env.NEXT_PUBLIC_DEVICE_FARM_MEDIA_WS_IDLE_CLOSE_MS = '0';

const sessionValues = new Map<string, string>();
const localValues = new Map<string, string>([
  ['device-farm:current-organization-id', 'org-a']
]);
Object.defineProperty(globalThis, 'window', {
  configurable: true,
  value: {
    addEventListener() {},
    removeEventListener() {},
    localStorage: {
      getItem(key: string): string | null {
        return localValues.get(key) ?? null;
      },
      setItem(key: string, value: string): void {
        localValues.set(key, value);
      },
      removeItem(key: string): void {
        localValues.delete(key);
      }
    },
    sessionStorage: {
      getItem(key: string): string | null {
        return sessionValues.get(key) ?? null;
      },
      setItem(key: string, value: string): void {
        sessionValues.set(key, value);
      }
    }
  }
});
Object.defineProperty(globalThis, 'location', {
  configurable: true,
  value: {
    protocol: 'http:',
    hostname: 'localhost'
  }
});
Object.defineProperty(globalThis, 'crypto', {
  configurable: true,
  value: {
    randomUUID: () => 'probe-session'
  }
});

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.CONNECTING;
  binaryType = '';
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((evt: { data: string | ArrayBuffer }) => void) | null = null;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  emitBinary(frame: ArrayBuffer): void {
    this.onmessage?.({ data: frame });
  }
}

function h264KeyFrame(serial: string): ArrayBuffer {
  const serialBytes = new TextEncoder().encode(serial);
  const payload = new Uint8Array([0x00, 0x00, 0x00, 0x02, 0x65, 0xaa]);
  const out = new Uint8Array(2 + serialBytes.length + 4 + 9 + payload.length);
  let offset = 0;
  out[offset++] = 0x11;
  out[offset++] = serialBytes.length;
  out.set(serialBytes, offset);
  offset += serialBytes.length;
  out.set([0x00, 0x01, 0x00, 0x01], offset);
  offset += 4;
  out[offset++] = 0x01;
  out.set([0, 0, 0, 0, 0, 0, 0, 1], offset);
  offset += 8;
  out.set(payload, offset);
  return out.buffer;
}

test('dedicated media websocket isolates H264 subscriptions per serial', async () => {
  FakeWebSocket.instances = [];
  (globalThis as unknown as { WebSocket: typeof FakeWebSocket }).WebSocket =
    FakeWebSocket;

  const receivedA: ArrayBuffer[] = [];
  const receivedB: ArrayBuffer[] = [];
  const { requestIdr, subscribeBinaryFrames } = await import('./ws.ts');

  const unsubscribeA = subscribeBinaryFrames((frame) => {
    receivedA.push(frame);
  }, 'A');
  const unsubscribeB = subscribeBinaryFrames((frame) => {
    receivedB.push(frame);
  }, 'B');

  assert.equal(FakeWebSocket.instances.length, 2);
  const socketA = FakeWebSocket.instances[0]!;
  const socketB = FakeWebSocket.instances[1]!;
  const urlA = new URL(socketA.url);
  const urlB = new URL(socketB.url);

  assert.equal(urlA.searchParams.get('session_id'), 'probe-session:media:A');
  assert.equal(urlB.searchParams.get('session_id'), 'probe-session:media:B');
  assert.equal(urlA.searchParams.get('org_id'), 'org-a');
  assert.equal(urlB.searchParams.get('org_id'), 'org-a');
  assert.notEqual(
    urlA.searchParams.get('session_id'),
    urlB.searchParams.get('session_id')
  );

  socketA.open();
  socketB.open();

  assert.deepEqual(
    socketA.sent.map((raw) => JSON.parse(raw)),
    [{ type: 'watch_serial', serial: 'A' }]
  );
  assert.deepEqual(
    socketB.sent.map((raw) => JSON.parse(raw)),
    [{ type: 'watch_serial', serial: 'B' }]
  );

  socketA.emitBinary(h264KeyFrame('A'));
  socketB.emitBinary(h264KeyFrame('B'));

  assert.equal(receivedA.length, 1);
  assert.equal(receivedB.length, 1);

  requestIdr('A', 0);

  assert.equal(FakeWebSocket.instances.length, 2);
  assert.deepEqual(JSON.parse(socketA.sent.at(-1)!), {
    type: 'request_idr',
    serial: 'A'
  });
  assert.deepEqual(JSON.parse(socketB.sent.at(-1)!), {
    type: 'watch_serial',
    serial: 'B'
  });

  unsubscribeA();
  unsubscribeB();
  socketA.close();
  socketB.close();
});
