import type { ContentItem } from '../services/api';
import {
  resolveCommentDisplayBody,
  shouldHideParentSecondary
} from './comment-display';

export interface CommentParentSummary {
  primary: string;
  secondary: string | null;
  postId: string | null;
  linkedParentId: string | null;
  source: string | null;
}

export interface CommentParentLabels {
  fallbackTitle: string;
  linkedTitle: string;
  postIdLabel: (shortId: string) => string;
}

const DEFAULT_LABELS: CommentParentLabels = {
  fallbackTitle: 'Original post',
  linkedTitle: 'Linked parent post',
  postIdLabel: (shortId) => `Post ${shortId}`
};

function objectValue(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function textValue(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const text = value.trim();
  return text || null;
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function commentParentSummary(
  item: Pick<
    ContentItem,
    | 'parent_id'
    | 'raw_data'
    | 'parent_item_hash'
    | 'parent_item_author'
    | 'parent_item_body'
    | 'body'
    | 'title'
    | 'content_type'
  >,
  labels: CommentParentLabels = DEFAULT_LABELS
): CommentParentSummary | null {
  const raw = objectValue(item.raw_data);
  const anchor = objectValue(raw?.parent_post_anchor);
  const author =
    textValue(item.parent_item_author) || textValue(anchor?.author);
  const timestamp = textValue(anchor?.timestamp);
  const text =
    textValue(item.parent_item_body) ||
    textValue(anchor?.text_prefix) ||
    textValue(raw?.parent_post_text) ||
    textValue(raw?.parent_text_prefix);
  const postId =
    textValue(raw?.parent_post_id) ||
    textValue(anchor?.pid) ||
    textValue(anchor?.fb_post_id) ||
    textValue(anchor?.stable_post_id) ||
    textValue(anchor?.post_key) ||
    null;
  const source =
    textValue(raw?.parent_context_source) ||
    textValue(raw?.parent_source) ||
    textValue(anchor?.source) ||
    null;

  const commentBody = resolveCommentDisplayBody(item);

  if (author || timestamp || text) {
    const secondary =
      text && !shouldHideParentSecondary(text, commentBody)
        ? truncate(text, 180)
        : null;
    return {
      primary: [author || labels.fallbackTitle, timestamp]
        .filter(Boolean)
        .join(' · '),
      secondary,
      postId,
      linkedParentId: item.parent_item_hash || item.parent_id,
      source
    };
  }

  if (postId) {
    return {
      primary: labels.postIdLabel(truncate(postId, 16)),
      secondary: null,
      postId,
      linkedParentId: item.parent_item_hash || item.parent_id,
      source
    };
  }

  const linkedParentId = item.parent_item_hash || item.parent_id;
  if (linkedParentId) {
    return {
      primary: labels.linkedTitle,
      secondary: truncate(linkedParentId, 16),
      postId: null,
      linkedParentId,
      source
    };
  }

  return null;
}
