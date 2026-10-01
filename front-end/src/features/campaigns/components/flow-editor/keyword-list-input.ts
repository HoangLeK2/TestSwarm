export function keywordInputValue(value: unknown): string {
  return Array.isArray(value) ? value.join(', ') : String(value ?? '');
}

export function keywordListFromInput(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

/**
 * Keep in-progress separators in the input while the parent stores a clean
 * keyword array. A genuinely different parent value still replaces the draft.
 */
export function reconcileKeywordInputDraft(
  draft: string,
  value: unknown,
  sameInput = true
): string {
  const persisted = Array.isArray(value)
    ? value.map(String)
    : keywordListFromInput(String(value ?? ''));

  return sameInput && keywordListsEqual(keywordListFromInput(draft), persisted)
    ? draft
    : keywordInputValue(value);
}

function keywordListsEqual(left: string[], right: string[]): boolean {
  return (
    left.length === right.length &&
    left.every((keyword, index) => keyword === right[index])
  );
}
