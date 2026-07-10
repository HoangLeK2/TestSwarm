import assert from 'node:assert/strict';
import test from 'node:test';

import {
  BinaryListenerRegistry,
  type BinaryListener
} from './binary-listener-registry';

const frame = new ArrayBuffer(1);

function listener(
  name: string,
  calls: string[],
  serial?: string
): BinaryListener {
  return {
    serial,
    fn: () => calls.push(name)
  };
}

test('dispatches a frame only to its serial listeners and unscoped listeners', () => {
  const registry = new BinaryListenerRegistry();
  const calls: string[] = [];

  registry.add(listener('all', calls));
  registry.add(listener('serial-a', calls, 'serial-a'));
  registry.add(listener('serial-b', calls, 'serial-b'));

  registry.dispatch(frame, 'serial-a');

  assert.deepEqual(calls, ['all', 'serial-a']);
});

test('preserves legacy fallback for binary frames without a parsed serial', () => {
  const registry = new BinaryListenerRegistry();
  const calls: string[] = [];

  registry.add(listener('all', calls));
  registry.add(listener('serial-a', calls, 'serial-a'));
  registry.add(listener('serial-b', calls, 'serial-b'));

  registry.dispatch(frame, null);

  assert.deepEqual(calls, ['all', 'serial-a', 'serial-b']);
});

test('removes listeners from both the count and serial index', () => {
  const registry = new BinaryListenerRegistry();
  const calls: string[] = [];
  const scoped = listener('serial-a', calls, 'serial-a');

  registry.add(scoped);
  assert.equal(registry.size, 1);
  assert.equal(registry.delete(scoped), true);
  assert.equal(registry.size, 0);

  registry.dispatch(frame, 'serial-a');
  assert.deepEqual(calls, []);
});

test('isolates listener errors while continuing serial dispatch', () => {
  const registry = new BinaryListenerRegistry();
  const calls: string[] = [];

  registry.add({
    serial: 'serial-a',
    fn: () => {
      throw new Error('decoder stopped');
    }
  });
  registry.add(listener('healthy', calls, 'serial-a'));

  assert.doesNotThrow(() => registry.dispatch(frame, 'serial-a'));
  assert.deepEqual(calls, ['healthy']);
});
