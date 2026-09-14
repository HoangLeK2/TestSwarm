import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const __dir = dirname(fileURLToPath(import.meta.url));

function readStageSource(): string {
  return readFileSync(join(__dir, 'multi-device-stage.tsx'), 'utf8');
}

test('multi-device follower grid positions virtual rows instead of stacking them', () => {
  const source = readStageSource();

  assert.equal(
    source.includes('rowVirtualizer.getTotalSize()'),
    true,
    'follower grid must reserve the full virtual scroll height'
  );
  assert.equal(
    source.includes('translateY(${virtualRow.start}px)'),
    true,
    'each follower grid row must be translated to its virtual row offset'
  );
});
