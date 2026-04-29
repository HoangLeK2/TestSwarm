"""
fb_extract package (refactor facade).

This repo historically used a single monolithic `tasks/fb_extract.py` module.
During refactor we keep a compatibility facade so all existing imports:

- `from tasks.fb_extract import ...` (including private `_...` symbols used by tests)
- `patch("tasks.fb_extract.time.sleep", ...)`

continue to work without changes.
"""

from __future__ import annotations

from . import _impl as _impl

# Re-export ALL names from `_core` (including private `_...` symbols).
# We intentionally include underscores because tests import them explicitly.
globals().update({k: v for k, v in _impl.__dict__.items() if not k.startswith("__")})

# Override moved implementations (so tests exercise the refactored code).
from .clustering import (  # noqa: E402
    _cluster_into_posts,
    _cluster_into_comments,
    _should_merge_post_nodes_despite_vertical_gap,
    _should_merge_split_comment_nodes,
)

from .post_extractor import (  # noqa: E402
    _merge_post_type,
    _maybe_fix_merged_feed_caption,
    _refresh_post_derived_hashes,
    _refine_comment_author_from_cluster,
)

globals().update(
    {
        "_cluster_into_posts": _cluster_into_posts,
        "_cluster_into_comments": _cluster_into_comments,
        "_should_merge_post_nodes_despite_vertical_gap": _should_merge_post_nodes_despite_vertical_gap,
        "_should_merge_split_comment_nodes": _should_merge_split_comment_nodes,
        "_merge_post_type": _merge_post_type,
        "_maybe_fix_merged_feed_caption": _maybe_fix_merged_feed_caption,
        "_refresh_post_derived_hashes": _refresh_post_derived_hashes,
        "_refine_comment_author_from_cluster": _refine_comment_author_from_cluster,
    }
)

__all__ = [k for k in globals().keys() if not k.startswith("__")]

