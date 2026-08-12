import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const __dir = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(__dir, '../../../../../../');

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

test('control-record flow editor uses virtualized default with explicit sort mode', () => {
  const flowEditor = readFlowEditorFile('flow-editor.tsx');
  const row = readFlowEditorFile('sortable-flow-row.tsx');
  const controlRecord = readFileSync(
    join(
      REPO_ROOT,
      'front-end/src/features/devices/components/control-record-view.tsx'
    ),
    'utf8'
  );

  assert.equal(
    flowEditor.includes('enableDragDrop?: boolean'),
    true,
    'FlowEditor must expose enableDragDrop for heavy control surfaces'
  );
  assert.equal(
    flowEditor.includes('virtualReorderMode?: boolean'),
    true,
    'FlowEditor must expose a lightweight reorder mode for virtualized control surfaces'
  );
  assert.equal(
    flowEditor.includes('useVirtualizer'),
    true,
    'FlowEditor must use virtualization when drag-and-drop is disabled'
  );
  assert.equal(
    flowEditor.includes('walkFlowStepsWithPaths'),
    true,
    'FlowEditor must flatten nested heavy scenarios before virtual rendering'
  );
  assert.equal(
    row.includes('function StaticFlowRow'),
    true,
    'FlowEditor must have a non-sortable row fallback'
  );
  assert.equal(
    controlRecord.includes('const [flowSortMode, setFlowSortMode]'),
    true,
    'control-record view must keep a sort-mode toggle instead of removing reorder'
  );
  assert.equal(
    controlRecord.includes('enableDragDrop={false}'),
    true,
    'control-record view must not restore the heavy dnd tree when sorting'
  );
  assert.equal(
    controlRecord.includes('virtualReorderMode={flowSortMode}'),
    true,
    'control-record view must use the virtualized reorder controls while sorting'
  );
});
