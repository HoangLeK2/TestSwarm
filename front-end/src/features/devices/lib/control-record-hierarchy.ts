export function resolveInteractionHierarchyXml(
  freshXml: string | null | undefined,
  cachedXml: string | null | undefined,
  options: { freshAttempted: boolean }
): string {
  const fresh = freshXml?.trim() ?? '';
  if (fresh) return fresh;
  if (options.freshAttempted) return '';
  return cachedXml?.trim() ?? '';
}

export function needsFreshMirrorSelectorXml(input: {
  selectorPickTarget: unknown;
  flowSelectorPickFgId: string | null | undefined;
}): boolean {
  return Boolean(input.selectorPickTarget || input.flowSelectorPickFgId);
}
