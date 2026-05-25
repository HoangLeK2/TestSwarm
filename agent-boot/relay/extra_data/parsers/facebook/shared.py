from __future__ import annotations

from typing import FrozenSet

XPATH_RECYCLER = (
    '//node[contains(@class, "RecyclerView") and @scrollable="true"]'
    '|//node[contains(@class, "StaggeredGridLayoutManager") and @scrollable="true"]'
)

XPATH_LIST = '//node[contains(@class, "ListView") and @scrollable="true"]'

COMMENT_BUTTON_TOKENS: FrozenSet[str] = frozenset(
    {
        "Bình luận",
        "Comment",
        "Comments",
    }
)

