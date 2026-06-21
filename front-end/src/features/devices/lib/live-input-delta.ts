export type LiveInputDelta =
  | { kind: 'append'; text: string }
  | { kind: 'delete'; count: number }
  | { kind: 'reset_append'; text: string };

/** Normalize to NFC so Vietnamese precomposed chars reach the device consistently. */
export function normalizeLiveInputText(text: string): string {
  return text.normalize('NFC');
}

/** Compute WS deltas between two local input snapshots for live device typing. */
export function computeLiveInputDeltas(
  prev: string,
  next: string
): LiveInputDelta[] {
  const from = normalizeLiveInputText(prev);
  const to = normalizeLiveInputText(next);
  if (from === to) return [];

  if (to.length > from.length && to.startsWith(from)) {
    const text = to.slice(from.length);
    return text ? [{ kind: 'append', text }] : [];
  }

  if (to.length < from.length && from.startsWith(to)) {
    const count = from.length - to.length;
    return count > 0 ? [{ kind: 'delete', count }] : [];
  }

  const deltas: LiveInputDelta[] = [];
  if (from.length > 0) {
    deltas.push({ kind: 'delete', count: from.length });
  }
  if (to.length > 0) {
    deltas.push({ kind: 'reset_append', text: to });
  }
  return deltas;
}
