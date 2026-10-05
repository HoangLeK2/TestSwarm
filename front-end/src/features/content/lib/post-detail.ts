import type { ContentItem } from '../services/api';

/** Top-level content items may show linked child comments on detail. */
export function shouldShowPostComments(
  item: Pick<ContentItem, 'item_level' | 'content_type' | 'collection'>
): boolean {
  if (item.item_level > 0) return false;
  return !item.content_type.endsWith('comment');
}
