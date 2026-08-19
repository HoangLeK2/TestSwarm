export type LiveInputDelta =
  | { kind: 'append'; text: string }
  | { kind: 'delete'; count: number }
  | { kind: 'reset_append'; text: string };

/** Normalize to NFC so Vietnamese precomposed chars reach the device consistently. */
export function normalizeLiveInputText(text: string): string {
  return text.normalize('NFC');
}

/**
 * Split into code points, not UTF-16 units: the device IME deletes one
 * *character* per DEL key, so surrogate pairs (emoji) would otherwise be
 * under-deleted by half.
 */
function toChars(text: string): string[] {
  return Array.from(text);
}

/** Compute WS deltas between two local input snapshots for live device typing. */
export function computeLiveInputDeltas(
  prev: string,
  next: string
): LiveInputDelta[] {
  const from = normalizeLiveInputText(prev);
  const to = normalizeLiveInputText(next);
  if (from === to) return [];

  const fromChars = toChars(from);
  const toChars_ = toChars(to);

  // Longest common prefix — a Telex/VNI keystroke only ever rewrites the tail
  // ("cha" → "chà"), so diffing from the prefix keeps the edit to 1 DEL + 1
  // append instead of clearing and retyping the whole field on every accent.
  let prefix = 0;
  const maxPrefix = Math.min(fromChars.length, toChars_.length);
  while (prefix < maxPrefix && fromChars[prefix] === toChars_[prefix]) {
    prefix += 1;
  }

  const deleteCount = fromChars.length - prefix;
  const appendText = toChars_.slice(prefix).join('');

  // Nothing in common: one atomic IME replace beats a DEL storm followed by an
  // append (fewer round-trips, and the field can never be observed half-erased).
  if (prefix === 0 && deleteCount > 0) {
    return to
      ? [{ kind: 'reset_append', text: to }]
      : [{ kind: 'delete', count: deleteCount }];
  }

  const deltas: LiveInputDelta[] = [];
  if (deleteCount > 0) deltas.push({ kind: 'delete', count: deleteCount });
  if (appendText) deltas.push({ kind: 'append', text: appendText });
  return deltas;
}
