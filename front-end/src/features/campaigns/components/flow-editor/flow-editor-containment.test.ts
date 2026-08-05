import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const __dir = dirname(fileURLToPath(import.meta.url));

function readFlowEditorFile(fileName: string): string {
  return readFileSync(join(__dir, fileName), 'utf8');
}

test('flow editor heavy rows do not use paint containment', () => {
  for (const fileName of [
    'sortable-flow-row.tsx',
    'step-card.tsx',
    'bracket-block.tsx'
  ]) {
    const source = readFlowEditorFile(fileName);
    assert.equal(
      source.includes("contain: 'layout paint style'"),
      false,
      `${fileName} must not use paint containment because nested heavy scenario rows can repaint blank while scrolling`
    );
  }
});
