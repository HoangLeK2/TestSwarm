export function formatOrgDisplayName(
  name: string | null | undefined,
  fallback = '—'
) {
  const n = (name ?? '').trim();
  return n.length ? n : fallback;
}
