import type { ContentItem } from '../services/api';

function objectValue(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function textValue(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const text = value.trim();
  return text || null;
}

function normalizeComparable(text: string): string {
  return text.trim().toLowerCase().replace(/\s+/g, ' ');
}

/** Hide parent excerpt when it is the same text as the comment body. */
export function shouldHideParentSecondary(
  parentText: string,
  commentBody: string
): boolean {
  const parent = normalizeComparable(parentText);
  const comment = normalizeComparable(commentBody);
  if (!parent || !comment) return false;
  if (parent === comment) return true;
  if (comment.includes(parent) || parent.includes(comment)) return true;
  return false;
}

/** Collapse repeated domains in link-preview scrape noise. */
export function dedupeLinkPreviewNoise(text: string): string {
  const trimmed = text.trim();
  const match = trimmed.match(/^(Liên kết được chia sẻ|Shared link):\s*(.+)$/i);
  if (!match) return trimmed;

  const label = match[1];
  const tokens = match[2]
    .split(/[\s,;]+/)
    .map((t) => t.trim())
    .filter(Boolean);
  const seen = new Set<string>();
  const unique: string[] = [];
  for (const token of tokens) {
    const key = token.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(token);
  }
  if (unique.length === 0) return trimmed;
  return `${label}: ${unique.join(', ')}`;
}

export function resolveCommentDisplayBody(
  item: Pick<ContentItem, 'body' | 'title' | 'raw_data'>
): string {
  const raw = objectValue(item.raw_data);
  const fromBody = textValue(item.body);
  const fromRaw = textValue(raw?.text);
  const fromTitle = textValue(item.title);

  const primary = fromBody || fromRaw || fromTitle || '';
  return dedupeLinkPreviewNoise(primary);
}

export function resolveCommentDisplayAuthor(
  item: Pick<ContentItem, 'author' | 'raw_data'>
): string | null {
  const raw = objectValue(item.raw_data);
  return textValue(item.author) || textValue(raw?.author);
}
