from __future__ import annotations

# Responsibility: XML -> nodes + top-level detection helpers.
from ._impl import (  # noqa: F401
    _parse_xml,
    _collect_text_nodes,
    _infer_screen_size,
    _hierarchy_is_fb_comment_sheet,
    _scan_special_screen,
)

# Convenience re-exports used by scenarios/tests indirectly via `tasks.fb_extract`.
from ._impl import (  # noqa: F401
    _parse_bounds,
    _pick_feed_container,
    _feed_comment_y_max,
)

__all__ = [
    "_parse_xml",
    "_collect_text_nodes",
    "_infer_screen_size",
    "_hierarchy_is_fb_comment_sheet",
    "_scan_special_screen",
    "_parse_bounds",
    "_pick_feed_container",
    "_feed_comment_y_max",
]

