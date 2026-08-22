"""Declared-mode matching for Vietnamese UI labels.

Every label list in the Facebook flows used to be a bare tuple of strings, and
the decision of *how* to match it lived at the call site — usually
``any(token in folded for token in TOKENS)``. That put the dangerous choice as
far as possible from the person making it: whoever adds a token to the list
cannot see that it will be matched as a substring, and Vietnamese folded to
ASCII makes substring matching catastrophic.

Measured against 2,563 real author names collected by this system:

===========  ===========================  =========================
token        folds to                     real people it discarded
===========  ===========================  =========================
``gỡ``       ``go``                       107 (Võ Ngọc Trầm, Sài Gòn)
``tham gia`` ``tham gia``                 31
``trang``    ``trang``                    23 (Minh Trang Đoàn)
``chặn``     ``chan``                     7  (Huy Chan, Trần Hữu Chánh)
``xóa``      ``xoa``                      3  (Xoan)
===========  ===========================  =========================

Every one of those failures is silent: the row is dropped, the flow reports
"no candidates", and nothing looks broken.

So the mode moves to the declaration. A :class:`LabelSet` cannot exist without
saying how its tokens are matched, and ``test_fb_label_guard.py`` refuses any
token that can collide with a Vietnamese name in the mode it declared.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Literal

__all__ = [
    "MODE_PHRASE",
    "MODE_WORD",
    "MODE_EXACT",
    "LabelSet",
    "fold",
    "registered_label_sets",
]

MODE_PHRASE = "phrase"
MODE_WORD = "word"
MODE_EXACT = "exact"

MatchMode = Literal["phrase", "word", "exact"]

_MODES = (MODE_PHRASE, MODE_WORD, MODE_EXACT)

_REGISTRY: list["LabelSet"] = []


def fold(value: object) -> str:
    """Lowercase, strip Vietnamese diacritics, collapse whitespace.

    This is the single normalisation used everywhere labels are compared. It is
    also precisely what makes naive matching unsafe: after folding, "Gỡ" and the
    middle of "Ngọc" are the same three characters.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = text.replace("đ", "d")
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class LabelSet:
    """A named group of tokens plus the one way they are allowed to match.

    ``mode`` picks the trade-off explicitly:

    ``phrase``
        substring of the folded text. Only for long, distinctive wording that
        no name can contain — ``"nguoi tham gia an danh"``.
    ``word``
        whole words, ``\\btoken\\b``. For short multi-word phrases that would be
        unsafe as substrings — ``"tham gia"``.
    ``exact``
        the folded text equals the token. For single short syllables that are
        also Vietnamese names — ``go``, ``xoa``, ``chan``. A button's label is
        the whole label; a person's row never is.

    ``collides_with_names`` is the escape hatch, and it costs a sentence of
    justification. Some collisions are worth keeping — refusing to tap a person
    named "An" loses one candidate, while tapping "Ẩn những người bạn có thể
    biết" destroys the account's suggestion source permanently. The point is not
    that collisions are forbidden; it is that they are decided, in writing,
    rather than discovered on a device three weeks later.
    """

    name: str
    tokens: tuple[str, ...]
    mode: MatchMode
    why: str = ""
    collides_with_names: tuple[str, ...] = ()
    collision_reason: str = ""
    _patterns: tuple[re.Pattern[str], ...] = field(
        default=(), init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise ValueError(
                f"LabelSet {self.name!r}: mode must be one of {_MODES}, "
                f"got {self.mode!r}"
            )
        if not self.tokens:
            raise ValueError(f"LabelSet {self.name!r}: needs at least one token")
        for token in self.tokens:
            if token != fold(token):
                raise ValueError(
                    f"LabelSet {self.name!r}: token {token!r} is not folded — "
                    f"write it as {fold(token)!r}"
                )
        unknown = tuple(t for t in self.collides_with_names if t not in self.tokens)
        if unknown:
            raise ValueError(
                f"LabelSet {self.name!r}: collides_with_names lists tokens that "
                f"are not in the set: {unknown}"
            )
        if self.collides_with_names and not self.collision_reason.strip():
            raise ValueError(
                f"LabelSet {self.name!r}: an accepted name collision needs a "
                f"collision_reason saying why the trade is worth it"
            )
        if self.mode == MODE_WORD:
            object.__setattr__(
                self,
                "_patterns",
                tuple(
                    re.compile(rf"\b{re.escape(token)}\b") for token in self.tokens
                ),
            )
        _REGISTRY.append(self)

    # ── matching ────────────────────────────────────────────────────────────

    def matches(self, text: object) -> bool:
        """True when any token matches ``text`` under this set's mode."""
        return self.first_match(text) != ""

    def matches_folded(self, folded: str) -> bool:
        """Same, for text the caller has already folded.

        Folding is the expensive half of a match — NFKD plus a whitespace
        regex, about 1.1us per label against 0.2us for the comparison itself.
        A predicate that consults two or three sets would otherwise fold the
        same string two or three times, and these run over every node in a
        hierarchy. The caller guarantees the input came from ``fold()``.
        """
        return self.first_match_folded(folded) != ""

    def first_match(self, text: object) -> str:
        """The first matching token, or ``""``. Callers report this to operators."""
        return self.first_match_folded(fold(text))

    def first_match_folded(self, folded: str) -> str:
        if not folded:
            return ""
        if self.mode == MODE_EXACT:
            return folded if folded in self.tokens else ""
        if self.mode == MODE_PHRASE:
            return next((t for t in self.tokens if t in folded), "")
        return next(
            (
                token
                for token, pattern in zip(self.tokens, self._patterns)
                if pattern.search(folded)
            ),
            "",
        )

    def all_matches(self, text: object) -> list[str]:
        """Every matching token, in declaration order. Used by scoring loops."""
        return self.all_matches_folded(fold(text))

    def all_matches_folded(self, folded: str) -> list[str]:
        if not folded:
            return []
        if self.mode == MODE_EXACT:
            return [folded] if folded in self.tokens else []
        if self.mode == MODE_PHRASE:
            return [t for t in self.tokens if t in folded]
        return [
            token
            for token, pattern in zip(self.tokens, self._patterns)
            if pattern.search(folded)
        ]

    def matches_any(self, texts: Iterable[object]) -> bool:
        return any(self.matches(text) for text in texts)

    def __iter__(self) -> Iterator[str]:
        return iter(self.tokens)

    def __contains__(self, token: object) -> bool:
        return fold(token) in self.tokens

    def __len__(self) -> int:
        return len(self.tokens)


def registered_label_sets() -> tuple[LabelSet, ...]:
    """Every LabelSet constructed so far, for the guard test to audit.

    Registration happens in ``__post_init__``, so importing the module that
    declares a set is enough — there is no separate list to forget to update.
    """
    return tuple(_REGISTRY)
