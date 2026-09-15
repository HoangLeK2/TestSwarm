import assert from 'node:assert/strict';
import test from 'node:test';

import {
  mockupOuterHeightPx,
  mockupScreenWidthForHeightPx
} from './device-android-frame-geometry';

test('fitted width never overflows the height it was fitted to', () => {
  const cases: Array<[number, number, number]> = [
    [700, 1080, 2400],
    [500, 1080, 2400],
    [320, 1080, 1920],
    [900, 1440, 3200],
    [400, 2400, 1080] // landscape
  ];
  for (const [maxHeight, dw, dh] of cases) {
    const width = mockupScreenWidthForHeightPx(maxHeight, dw, dh);
    assert.ok(width > 0, `expected a positive width for ${maxHeight}px`);
    assert.ok(
      mockupOuterHeightPx(width, dw, dh) <= maxHeight,
      `${width}px frame overflows ${maxHeight}px for ${dw}x${dh}`
    );
  }
});
