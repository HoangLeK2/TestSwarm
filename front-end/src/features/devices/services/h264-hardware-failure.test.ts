import assert from 'node:assert/strict';
import test from 'node:test';

import { createH264HardwareFailureRegistry } from './h264-hardware-failure';

function createStorage() {
  const values = new Map<string, string>();
  return {
    getItem(key: string) {
      return values.get(key) ?? null;
    },
    setItem(key: string, value: string) {
      values.set(key, value);
    }
  };
}

test('hardware decode failures are remembered per device serial', () => {
  const storage = createStorage();
  const registry = createH264HardwareFailureRegistry(() => storage);

  registry.remember('serial-a');

  assert.equal(registry.has('serial-a'), true);
  assert.equal(registry.has('serial-b'), false);
});

test('hardware decode failures survive worker remount for the same serial', () => {
  const storage = createStorage();
  createH264HardwareFailureRegistry(() => storage).remember('serial-a');

  const remountedRegistry = createH264HardwareFailureRegistry(() => storage);

  assert.equal(remountedRegistry.has('serial-a'), true);
  assert.equal(remountedRegistry.has('serial-b'), false);
});
