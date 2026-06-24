import { describe, expect, it } from 'vitest';
import {
  computeLiveInputDeltas,
  normalizeLiveInputText
} from './live-input-delta';

describe('computeLiveInputDeltas', () => {
  it('returns empty when unchanged', () => {
    expect(computeLiveInputDeltas('abc', 'abc')).toEqual([]);
  });

  it('appends suffix', () => {
    expect(computeLiveInputDeltas('open', 'openclaw')).toEqual([
      { kind: 'append', text: 'claw' }
    ]);
  });

  it('deletes trailing chars', () => {
    expect(computeLiveInputDeltas('openclaw', 'open')).toEqual([
      { kind: 'delete', count: 4 }
    ]);
  });

  it('resets on paste or middle edit', () => {
    expect(computeLiveInputDeltas('abc', 'xyz')).toEqual([
      { kind: 'delete', count: 3 },
      { kind: 'reset_append', text: 'xyz' }
    ]);
  });

  it('normalizes vietnamese to NFC before diffing', () => {
    const nfd = 'e\u0301'; // é as e + combining acute
    const nfc = '\u00e9';
    expect(normalizeLiveInputText(nfd)).toBe(nfc);
    expect(computeLiveInputDeltas('', nfd)).toEqual([
      { kind: 'append', text: nfc }
    ]);
  });
});
