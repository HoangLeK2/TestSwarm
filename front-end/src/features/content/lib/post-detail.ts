import type { ContentItem } from '../services/api';

/** Top-level Facebook group feed posts should show linked comments on detail. */
export function shouldShowPostComments(
  item: Pick<ContentItem, 'item_level' | 'content_type' | 'collection'>
): boolean {
  if (item.item_level > 0) return false;
  if (item.content_type === 'fb_comment') return false;
  if (item.collection === 'fb_group_posts') return true;
  return item.content_type === 'fb_post';
}
