from __future__ import annotations

from .clustering import (
    _cluster_into_comments,
    _cluster_into_posts,
    _should_merge_post_nodes_despite_vertical_gap,
    _should_merge_split_comment_nodes,
)
from .comment_pipeline import (
    _extract_comment,
    _find_binh_luan_button_bounds_in_element,
    _find_binh_luan_button_in_element,
    _legacy_last_binh_luan_anchors,
    _post_id_from_ctx,
    _resolve_comment_region_anchors,
    parse_fb_comments_from_xml,
    parse_fb_comments_from_xml_with_diagnostic,
    resolve_center_comment_target_from_xml,
    resolve_comment_targets_from_xml,
    resolve_topmost_comment_target_from_xml,
)
from .constants import _AUTHOR_PREFIXES, _RE_LINK_TYPE, _RE_POST_RESHARE_HEADER, _author_prefix_match
from .dedup import _dedup, _dedup_comments
from .expansion_runtime import _expand_see_more, expand_see_more_with_lazy_hydration, prefetch_viewport_scrolls
from .feed_pipeline import (
    _empty_post_diagnostic,
    _extract_header_stats,
    _extract_posts_from_recycler,
    is_fb_post_truncated,
    parse_fb_posts_from_xml,
    parse_fb_posts_from_xml_with_diagnostic,
)
from .filters import (
    _comment_line_is_badge,
    _is_comment_left_avatar_name_strip,
    _is_comment_reaction_count_row,
    _is_comment_row_parse_noise,
    _is_compact_comment_action_label,
    _is_cmt_noise,
    _is_duplicate_short_author_footer_row,
    _is_junk_parsed_comment_row,
    _is_junk_recycler_post,
    _keep_soft_junk,
    _looks_like_comment_timestamp_row,
    _post_body_has_comment_thread_a11y,
)
from .parser import (
    _collect_text_nodes,
    _cy,
    _feed_comment_y_max,
    _hierarchy_is_fb_comment_sheet,
    _infer_screen_size,
    _normalize_fb_ui_spacing,
    _parse_bounds,
    _parse_xml,
    _pick_feed_container,
    _recycler_item_top_y_sort_key,
    _scan_special_screen,
    _score_feed_container,
)
from .post_extractor import (
    _extract_fb_link_meta,
    _extract_media_artifacts,
    _extract_post,
    _maybe_fix_merged_feed_caption,
    _merge_post_type,
    _refresh_post_derived_hashes,
    _refine_comment_author_from_cluster,
    _resource_id_media_hint,
    _structural_post_type_hint,
)
from .shared import COMMENT_BUTTON_TOKENS as _COMMENT_BUTTON_TOKENS
from .ui_expansion import _collect_see_more_tap_plan
from .group_pipeline import parse_group_search_results

__all__ = [k for k in globals().keys() if not k.startswith("__")]
