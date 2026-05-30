import assert from 'node:assert/strict';
import test from 'node:test';

import { filenameFromContentDisposition } from './download.ts';

test('filenameFromContentDisposition parses quoted filename', () => {
  const name = filenameFromContentDisposition(
    'attachment; filename="content_abc_screenshot.png"'
  );
  assert.equal(name, 'content_abc_screenshot.png');
});
