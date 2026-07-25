import assert from 'node:assert/strict';
import test from 'node:test';
import { createScrcpyViewerSession } from './scrcpy-viewer-session';

test('viewer sessions are stable per serial but isolated per mounted screen', () => {
  let sequence = 0;
  const createId = (role: string) => `${role}:viewer-${++sequence}`;
  const first = createScrcpyViewerSession('control-screen', createId);
  const second = createScrcpyViewerSession('control-screen', createId);

  assert.equal(first.idFor('serial-a'), 'control-screen:viewer-1');
  assert.equal(first.idFor('serial-a'), 'control-screen:viewer-1');
  assert.equal(first.idFor('serial-b'), 'control-screen:viewer-2');
  assert.equal(second.idFor('serial-a'), 'control-screen:viewer-3');
});
