/**
 * Steps whose behaviour is platform-specific but whose *name* is not.
 *
 * These render a platform picker in the detail panel; the backend resolves the
 * actual implementation through the social_ext registry, so a node never has to
 * be duplicated per network.
 *
 * Kept in sync with SOCIAL_STEP_TYPES in
 * device_farm/services/social_ext/contract.py.
 */
export const PLATFORM_AWARE_STEP_TYPES = new Set<string>([
  'platform_session_gate',
  'lease_connection_candidate',
  'social_select_target',
  'social_connect_visible_people',
  'social_find_comment_button',
  'social_tap_comment_target',
  'social_apply_comment_filter',
  'social_open_comments',
  'social_scan_posts_interact',
  'social_open_author_from_post_match',
  'social_open_commenter_from_post_match',
  'content_interaction',
  'connection_request',
  'community_membership'
]);
