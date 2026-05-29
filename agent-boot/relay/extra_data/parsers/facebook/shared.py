from __future__ import annotations

from typing import FrozenSet

# Many devices (e.g. Vivo) omit scrollable="true" on RecyclerView in hierarchy dumps.
XPATH_RECYCLER = (
    '//node[contains(@class, "RecyclerView")]'
    '|//node[contains(@class, "StaggeredGridLayoutManager")]'
)

XPATH_LIST = '//node[contains(@class, "ListView") and @scrollable="true"]'

COMMENT_BUTTON_TOKENS: FrozenSet[str] = frozenset(
    {
        "Bình luận",
        "Comment",
        "Comments",
    }
)

